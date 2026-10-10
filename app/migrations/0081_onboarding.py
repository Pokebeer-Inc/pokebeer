from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0080_beer_draft'),
    ]

    operations = [
        migrations.AddField(
            model_name='beeruser',
            name='birth_date',
            field=models.DateField(blank=True, null=True, verbose_name='Date de naissance'),
        ),
        migrations.AddField(
            model_name='beeruser',
            name='gender',
            field=models.CharField(blank=True, choices=[('femme', 'Femme'), ('homme', 'Homme'), ('autre', 'Autre'), ('nsp', 'Je préfère ne pas dire')], default='', max_length=5, verbose_name='Genre'),
        ),
        # Les comptes qui existent déjà n'ont rien à passer : ils reçoivent True ; les nouveaux comptes partent de False
        migrations.AddField(
            model_name='beeruser',
            name='onboarding_done',
            field=models.BooleanField(default=True, verbose_name='Inscription terminée'),
        ),
        migrations.AlterField(
            model_name='beeruser',
            name='onboarding_done',
            field=models.BooleanField(default=False, help_text="Faux tant que le membre n'a pas passé les pages qui suivent l'inscription ; les comptes existants sont considérés terminés.", verbose_name='Inscription terminée'),
        ),
    ]
