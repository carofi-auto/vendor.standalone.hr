import hmac

from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from drf_yasg import openapi
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from horilla_api.docs import document_api

from ...api_serializers.auth.serializers import (
    GetEmployeeSerializer,
    LoginRequestSerializer,
    PasswordResetSerializer,
)


class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    # The only unauthenticated write path in the API. django-axes locks an
    # account after repeated *failed* passwords, but counts nothing when the
    # credentials are valid -- so a leaked password can be replayed to mint
    # tokens as fast as the server answers. ScopedRateThrottle bounds that
    # by IP, on top of the axes lockout.
    throttle_scope = "login"

    @document_api(
        operation_description="Authenticate user and return JWT access token with employee info",
        request_body=LoginRequestSerializer,
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "employee": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "full_name": openapi.Schema(type=openapi.TYPE_STRING),
                            "employee_profile": openapi.Schema(
                                type=openapi.TYPE_STRING,
                                description="Profile image URL",
                            ),
                        },
                    ),
                    "access": openapi.Schema(
                        type=openapi.TYPE_STRING, description="JWT access token"
                    ),
                    "face_detection": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "face_detection_image": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Face detection image URL",
                        nullable=True,
                    ),
                    "geo_fencing": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    "company_id": openapi.Schema(
                        type=openapi.TYPE_INTEGER, nullable=True
                    ),
                },
            ),
        },
        tags=["auth"],
    )
    def post(self, request):
        if "username" in request.data and "password" in request.data:
            username = request.data.get("username")
            password = request.data.get("password")
            # Pass `request`: django-axes needs it to attribute the attempt to
            # a client and enforce the lockout. Without it the API login is
            # exempt from the brute-force protection the HTML login has --
            # and axes raises rather than silently allowing it.
            user = authenticate(request, username=username, password=password)
            if user:
                refresh = RefreshToken.for_user(user)
                employee = user.employee_get
                face_detection = False
                face_detection_image = None
                geo_fencing = False
                company_id = None
                # Each of these is optional configuration: get_company() can
                # return None, the face_detection and geo_fencing reverse
                # one-to-ones need not exist, and an ImageField with no file
                # raises on .url. Narrowed from bare excepts so a genuine
                # failure in this block is logged instead of silently
                # degrading the login response.
                company = employee.get_company()
                if company is not None:
                    company_id = company.id
                    try:
                        face_detection = company.face_detection.start
                    except (ObjectDoesNotExist, AttributeError):
                        pass
                    try:
                        geo_fencing = company.geo_fencing.start
                    except (ObjectDoesNotExist, AttributeError):
                        pass
                try:
                    face_detection_image = employee.face_detection.image.url
                except (ObjectDoesNotExist, AttributeError, ValueError):
                    pass
                result = {
                    "employee": GetEmployeeSerializer(employee).data,
                    "access": str(refresh.access_token),
                    "face_detection": face_detection,
                    "face_detection_image": face_detection_image,
                    "geo_fencing": geo_fencing,
                    "company_id": company_id,
                }
                return Response(result, status=200)
            else:
                # A locked-out caller must be told so, not handed another 401.
                # AxesStandaloneBackend returns None rather than raising, so
                # without this check axes counts the failures but never blocks
                # -- the API would keep accepting guesses past the limit while
                # the HTML login stops at five.
                if AxesProxyHandler.is_locked(
                    request, credentials={"username": username}
                ):
                    return Response(
                        {
                            "error": _(
                                "Too many failed login attempts. Try again later."
                            )
                        },
                        status=429,
                    )
                return Response({"error": _("Invalid credentials")}, status=401)
        else:
            return Response(
                {"error": _("Please provide Username and Password")}, status=400
            )


class PasswordResetAPIView(APIView):
    """
    Allows an authenticated employee to change their own password.

    GET  — returns the fields required for the reset form.
    POST — verifies the old password and saves the new one.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "login"

    def get(self, _request):
        return Response(
            {"fields": ["old_password", "new_password", "confirm_password"]},
            status=200,
        )

    def post(self, request):
        serializer = PasswordResetSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        return Response({"message": _("Password updated successfully.")}, status=200)



class InternalTokenExchangeView(APIView):
    """
    Passwordless service-to-service token exchange used by the carofi BFF.

    A trusted internal caller (e.g. server.connect.admin) presents a shared
    service token in the ``X-Internal-Service-Token`` header along with an
    employee email; on success this view returns a per-employee JWT access
    token issued via ``RefreshToken.for_user`` so all downstream horilla
    permission checks behave exactly as they would for a normal login.

    Intended only for the ~47 carofi internal employees who do not have
    Google accounts and therefore cannot use the social-login flow.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @document_api(
        operation_description=(
            "Internal service-to-service token exchange. Requires a shared "
            "service token in the X-Internal-Service-Token header. Returns a "
            "JWT scoped to the employee identified by the supplied email."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["email"],
            properties={
                "email": openapi.Schema(type=openapi.TYPE_STRING),
            },
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "access": openapi.Schema(type=openapi.TYPE_STRING),
                    "expires_in": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "employee_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                    "is_reporting_manager": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                },
            ),
            401: "Missing or invalid service token",
            404: "No matching employee",
        },
        tags=["auth"],
    )
    def post(self, request):
        expected_token = getattr(settings, "CAROFI_INTERNAL_SERVICE_TOKEN", "") or ""
        provided_token = request.headers.get("X-Internal-Service-Token", "") or ""

        if not expected_token or not hmac.compare_digest(
            provided_token, expected_token
        ):
            return Response({"error": "invalid_service_token"}, status=401)

        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "email_required"}, status=400)

        try:
            employee = Employee.objects.select_related("employee_user_id").get(
                email__iexact=email
            )
        except Employee.DoesNotExist:
            return Response({"error": "employee_not_found"}, status=404)

        user = employee.employee_user_id
        if user is None:
            return Response({"error": "employee_user_not_linked"}, status=404)

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        expires_in = int(access.lifetime.total_seconds())

        is_reporting_manager = EmployeeWorkInformation.objects.filter(
            reporting_manager_id=employee
        ).exists()

        return Response(
            {
                "access": str(access),
                "expires_in": expires_in,
                "employee_id": employee.id,
                "is_reporting_manager": is_reporting_manager,
            },
            status=200,
        )
