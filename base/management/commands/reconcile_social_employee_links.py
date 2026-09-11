"""
Reconcile employee->user links using existing social-auth records.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from employee.models import Employee


class Command(BaseCommand):
    """
    Align employee records with social-auth users by email.
    """

    help = "Reconcile employee_user_id with social login users by email"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            type=str,
            default="google-oauth2",
            help="Social auth provider name (default: google-oauth2)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to database",
        )

    def handle(self, *args, **options):
        try:
            from social_django.models import UserSocialAuth
        except Exception:
            self.stdout.write(
                self.style.ERROR(
                    "social_django is not installed or migrations are missing in this environment."
                )
            )
            return

        provider = options["provider"]
        dry_run = options["dry_run"]

        socials = UserSocialAuth.objects.filter(provider=provider).select_related("user")
        total = socials.count()
        relinked = 0
        skipped = 0

        self.stdout.write(
            f"Scanning {total} social users for provider '{provider}' (dry_run={dry_run})..."
        )

        for social in socials:
            user = social.user
            email = (user.email or "").strip().lower()
            if not email and "@" in (user.username or ""):
                email = user.username.strip().lower()

            if not email:
                skipped += 1
                continue

            employee = Employee.objects.filter(email__iexact=email).first()
            if employee is None:
                skipped += 1
                continue

            current_user = employee.employee_user_id
            if current_user and current_user.id == user.id:
                continue

            relinked += 1
            old_user_id = current_user.id if current_user else None
            self.stdout.write(
                f"- Employee {employee.id} ({email}) link: {old_user_id} -> {user.id}"
            )

            if dry_run:
                continue

            with transaction.atomic():
                if current_user and current_user.id != user.id:
                    user.groups.add(*current_user.groups.all())
                    user.user_permissions.add(*current_user.user_permissions.all())
                    if hasattr(current_user, "is_new_employee"):
                        user.is_new_employee = current_user.is_new_employee
                        user.save(update_fields=["is_new_employee"])

                employee.employee_user_id = user
                employee.save(update_fields=["employee_user_id"])

        summary = (
            f"Done. total={total}, relinked={relinked}, skipped={skipped}, dry_run={dry_run}"
        )
        self.stdout.write(self.style.SUCCESS(summary))

