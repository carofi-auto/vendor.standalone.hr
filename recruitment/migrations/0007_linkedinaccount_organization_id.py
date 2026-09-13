from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Carofi: add LinkedInAccount.organization_id.

    Carried over from the fork's 1.x tree, where the field was introduced so job
    posts are authored by the company Page (urn:li:organization:<id>) instead of
    the token owner's personal feed (urn:li:person:<sub_id>).

    Additive and non-destructive: a CharField with default="" and no null=True,
    so the ALTER TABLE backfills existing rows with the empty string and
    recruitment/views/linkedin.py treats empty as "not configured" and refuses
    to post rather than falling back to the personal feed.

    LinkedInAccount is not registered with simple_history, so there is no
    corresponding historical model to alter.
    """

    dependencies = [
        ("recruitment", "0006_alter_rejectreason_options_alter_skillzone_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="linkedinaccount",
            name="organization_id",
            field=models.CharField(
                default="",
                help_text=(
                    "Numeric LinkedIn organization ID (e.g. 93254216). Posts "
                    "will be authored by this Company Page. Requires "
                    "w_organization_social scope on the token and admin rights "
                    "on the page."
                ),
                max_length=50,
                verbose_name="LinkedIn Page ID",
            ),
        ),
    ]
