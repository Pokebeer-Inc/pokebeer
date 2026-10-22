"""Le champ `style` d'une bière (« IPA, Stout ») est structuré : styles liés dans l'ordre, style principal. La famille copiée sur la bière disparaît :
elle se lit désormais sur le style principal (`primary_style.family`).

Un style absent du référentiel devient un style « à valider » (non officiel, sans famille) au lieu de rester un simple texte. Réversible : la
famille est recopiée en texte sur les bières, les liens sont supprimés."""
import django.db.models.deletion
from django.db import migrations, models

from app.validators import plain_text_validator
from app.domain import style_structure


def _models(apps):
    return style_structure.Models(apps.get_model('app', 'Style'), apps.get_model('app', 'BeerStyle'), apps.get_model('app', 'Beer'))


def build_structure(apps, schema_editor):
    models_ = _models(apps)
    registry = style_structure.Registry(models_.Style.objects.all())
    beers = models_.Beer.objects.exclude(style__isnull=True).exclude(style='')
    style_structure.rebuild(beers, models_, registry)


def restore_family_texts(apps, schema_editor):
    Beer = apps.get_model('app', 'Beer')
    for beer in Beer.objects.filter(primary_style__family__isnull=False).select_related('primary_style__family'):
        beer.style_family = beer.primary_style.family.name
        beer.save(update_fields=['style_family'])


class Migration(migrations.Migration):

    dependencies = [('app', '0098_style_families')]

    operations = [
        migrations.CreateModel(
            name='BeerStyle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('beer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='beer_styles', to='app.beer')),
                ('style', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='beer_styles', to='app.style')),
            ],
            options={'ordering': ['position']},
        ),
        migrations.AddIndex(model_name='beerstyle', index=models.Index(fields=['style', 'beer'], name='beerstyle_style_beer_idx')),
        migrations.AddConstraint(model_name='beerstyle', constraint=models.UniqueConstraint(fields=('beer', 'style'), name='unique_style_per_beer')),
        migrations.AddField(
            model_name='beer', name='primary_style',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='primary_beers', to='app.style'),
        ),
        migrations.AddField(
            model_name='beer', name='styles',
            field=models.ManyToManyField(editable=False, related_name='beers', through='app.BeerStyle', to='app.style'),
        ),
        migrations.AlterField(
            model_name='beer', name='style',
            field=models.CharField(blank=True, max_length=100, null=True, validators=[plain_text_validator], verbose_name='Style (ex: IPA, Stout...)'),
        ),
        migrations.AlterField(
            model_name='style', name='is_official',
            field=models.BooleanField(default=True, help_text='Décoché : saisi par un membre, en attente de validation.', verbose_name='Officiel'),
        ),
        migrations.RunPython(build_structure, restore_family_texts),
        migrations.RemoveField(model_name='beer', name='style_family'),
    ]
