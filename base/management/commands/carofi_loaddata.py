"""
loaddata with model save/delete signals disconnected.

Why this exists
---------------
Loading fixtures through the ORM fires every application signal, and Horilla has
eleven pre_save/post_save receivers that do not honour Django's ``raw`` kwarg --
the kwarg that exists precisely so a handler can tell "a fixture is being
installed" from "a user did something". During ``loaddata`` they run anyway.

That is not a tidiness problem. Two concrete examples found while rebuilding the
v1 database onto 2.x:

``employee.bonus_post_save``
    creates a BonusPoint for every Employee, so loading 86 employees manufactures
    86 bonus points that then collide with the fixture's own rows on
    ``UNIQUE(employee_id)``.

``leave.auto_approve_self_approval_stage``
    ``if created and instance.manager_id == instance.leave_request_id.employee_id:
    sender.objects.filter(pk=instance.pk).update(is_approved=True)``.
    Every fixture row arrives with ``created=True``, so this would overwrite
    stored approval state -- rewriting leave-approval history as a side effect of
    a migration. Data that was never approved would come out approved.

Others create settings rows and initial stages, and ``horilla_meet`` reaches out
to Google. None of that belongs in a data migration.

The alternative was patching eleven upstream handlers, which deepens exactly the
fork divergence this 2.x migration exists to reduce, and silently breaks the next
time upstream adds a twelfth. Disconnecting for the duration of the load is one
file, needs no upstream edits, and is inherently complete.

Usage
-----
Identical to ``loaddata``::

    python manage.py carofi_loaddata a.json b.json --ignorenonexistent

Caveat
------
Signals that legitimately POPULATE derived state are suppressed too, so anything
a receiver would have created must be present in the fixtures or reconciled
afterwards. That is the right trade: a fixture load should reproduce the source
data exactly, not re-derive it.
"""

from django.core.management.commands.loaddata import Command as LoadDataCommand
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)

SIGNALS = (pre_save, post_save, pre_delete, post_delete, m2m_changed)


class Command(LoadDataCommand):
    help = "loaddata, with model save/delete signals disconnected for the duration."

    def handle(self, *fixture_labels, **options):
        stashed = {}
        for sig in SIGNALS:
            # Copy the receiver list, then empty it. sender_receivers_cache is a
            # per-sender memo of "which receivers apply"; it must be cleared or
            # senders already seen keep firing from the cached list.
            stashed[sig] = sig.receivers[:]
            sig.receivers = []
            sig.sender_receivers_cache.clear()

        self.stdout.write(
            "carofi_loaddata: disconnected %d receiver(s) across %d signal(s)"
            % (sum(len(r) for r in stashed.values()), len(SIGNALS))
        )
        try:
            super().handle(*fixture_labels, **options)
        finally:
            # finally, not else: a failed load must not leave the process with
            # signals detached, or anything running afterwards in the same
            # process silently loses its application logic.
            for sig, receivers in stashed.items():
                sig.receivers = receivers
                sig.sender_receivers_cache.clear()
            self.stdout.write("carofi_loaddata: signals reconnected")
