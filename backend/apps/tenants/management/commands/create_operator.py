from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant, TenantMember


class Command(BaseCommand):
    help = "Create a dashboard operator and link to a tenant."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--tenant-name", default=None)

    def handle(self, *args, **opts):
        email = opts["email"]
        password = opts["password"]

        tenant = (
            Tenant.objects.filter(name=opts["tenant_name"]).first()
            if opts["tenant_name"] else Tenant.objects.first()
        )
        if not tenant and opts["tenant_name"]:
            tenant = Tenant.objects.create(name=opts["tenant_name"])
        if not tenant:
            self.stderr.write("No tenant exists.")
            return

        user, created = User.objects.get_or_create(
            username=email, defaults={"email": email, "is_staff": True}
        )
        user.set_password(password)
        user.save()

        TenantMember.objects.update_or_create(user=user, defaults={"tenant": tenant, "role": "admin"})
        self.stdout.write(self.style.SUCCESS(
            f"Operator {email} → tenant {tenant.name} ({tenant.id})"
        ))
        