import hmac

from django.conf import settings
from django.contrib.auth import authenticate
from drf_yasg import openapi
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from employee.models import Employee, EmployeeWorkInformation
from horilla_api.docs import document_api

from ...api_serializers.auth.serializers import (
    GetEmployeeSerializer,
    LoginRequestSerializer,
)


class LoginAPIView(APIView):
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
        if "username" and "password" in request.data.keys():
            username = request.data.get("username")
            password = request.data.get("password")
            user = authenticate(username=username, password=password)
            if user:
                refresh = RefreshToken.for_user(user)
                employee = user.employee_get
                face_detection = False
                face_detection_image = None
                geo_fencing = False
                company_id = None
                try:
                    face_detection = employee.get_company().face_detection.start
                except:
                    pass
                try:
                    geo_fencing = employee.get_company().geo_fencing.start
                except:
                    pass
                try:
                    face_detection_image = employee.face_detection.image.url
                except:
                    pass
                try:
                    company_id = employee.get_company().id
                except:
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
                return Response({"error": "Invalid credentials"}, status=401)
        else:
            return Response({"error": "Please provide Username and Password"})


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
