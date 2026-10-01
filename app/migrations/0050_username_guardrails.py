from django.db import migrations, models
from django.db.models.functions import Lower

import app.validators


def refuse_case_insensitive_duplicates(apps, schema_editor):
    """La contrainte échouerait sur des pseudos qui ne diffèrent que par la casse : on le dit avant, avec la liste."""
    BeerUser = apps.get_model('app', 'BeerUser')
    duplicates = (
        BeerUser.objects.annotate(lowered=Lower('username')).values('lowered')
        .annotate(total=models.Count('id')).filter(total__gt=1).values_list('lowered', flat=True)
    )
    duplicates = list(duplicates)
    if duplicates:
        raise RuntimeError(
            "Pseudos en double (casse ignorée), à renommer avant de migrer : " + ", ".join(sorted(duplicates))
        )


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0049_public_slugs_required'),
    ]

    operations = [
        migrations.RunPython(refuse_case_insensitive_duplicates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='beeruser',
            name='username',
            field=models.CharField(max_length=150, unique=True, validators=[app.validators.username_validator]),
        ),
        migrations.AddConstraint(
            model_name='beeruser',
            constraint=models.UniqueConstraint(Lower('username'), name='unique_username_ci', violation_error_message='Ce pseudo est déjà utilisé.'),
        ),
    ]
