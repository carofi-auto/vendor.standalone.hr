"""
Custom social-auth pipeline helpers for Horilla.
"""

from employee.models import Employee


def link_employee_by_email(strategy, details, user=None, *args, **kwargs):
    """
    Ensure the employee record is linked to the authenticated social user.

    For Google logins, this prevents a mismatch where permissions are assigned to
    one Django user while the employee profile points to another one.
    """
    if user is None:
        return

    email = (getattr(user, "email", "") or details.get("email") or "").strip().lower()
    if not email:
        return

    employee = Employee.objects.filter(email__iexact=email).first()
    if employee is None:
        return

    current_user = employee.employee_user_id
    if current_user and current_user.id == user.id:
        return

    if current_user and current_user.id != user.id:
        user.groups.add(*current_user.groups.all())
        user.user_permissions.add(*current_user.user_permissions.all())
        if hasattr(current_user, "is_new_employee"):
            user.is_new_employee = current_user.is_new_employee
            user.save(update_fields=["is_new_employee"])

    employee.employee_user_id = user
    employee.save(update_fields=["employee_user_id"])

