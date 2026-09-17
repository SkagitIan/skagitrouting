from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the read-only Routing Auditors group."

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name="Routing Auditors")
        permissions = Permission.objects.filter(
            content_type__app_label="routing",
            codename__startswith="view_",
        )
        group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS(f"Routing Auditors ready with {permissions.count()} view permissions."))
