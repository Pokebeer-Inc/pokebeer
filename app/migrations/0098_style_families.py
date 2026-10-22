"""Les familles de styles deviennent une table : plus de faute de frappe qui crée une famille de plus, un ordre d'affichage, un renommage en un geste.

`Style.family` (texte) est copié dans `StyleFamily` puis remplacé par une clé étrangère. Réversible : le nom de la famille est recopié en texte."""
import django.db.models.deletion
from django.db import migrations, models

from app.validators import plain_text_validator
from app.domain import style_catalog



def texts_to_families(apps, schema_editor):
    StyleFamily, Style = apps.get_model('app', 'StyleFamily'), apps.get_model('app', 'Style')
    order = {name: position for position, name in enumerate(style_catalog.FAMILIES)}
    families = {}
    for name in Style.objects.order_by().values_list('family', flat=True).distinct():
        families[name] = StyleFamily.objects.create(name=name, position=order.get(name, len(order)))
    for style in Style.objects.all():
        style.family_ref = families[style.family]
        style.save(update_fields=['family_ref'])


def families_to_texts(apps, schema_editor):
    Style = apps.get_model('app', 'Style')
    Style.objects.filter(is_official=False).delete()  # les styles « à valider » n'existaient pas : seul le texte de la bière les gardait
    for style in Style.objects.select_related('family_ref'):
        style.family = style.family_ref.name if style.family_ref else ''
        style.save(update_fields=['family'])


class Migration(migrations.Migration):

    dependencies = [('app', '0097_beer_without_brewery')]

    operations = [
        migrations.CreateModel(
            name='StyleFamily',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True, validators=[plain_text_validator], verbose_name='Nom')),
                ('position', models.PositiveSmallIntegerField(default=0, verbose_name="Ordre d'affichage")),
            ],
            options={'verbose_name': 'Famille de styles', 'verbose_name_plural': 'Familles de styles', 'ordering': ['position', 'name']},
        ),
        migrations.AlterModelOptions(name='style', options={'ordering': ['name'], 'verbose_name': 'Style de bière', 'verbose_name_plural': 'Styles de bière'}),
        migrations.AddField(
            model_name='style', name='is_official',
            field=models.BooleanField(default=True, help_text='Décoché : saisi par un membre, en attente de validation.', verbose_name='Officiel'),
        ),
        migrations.AddField(
            model_name='style', name='family_ref',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='styles', to='app.stylefamily'),
        ),
        migrations.RunPython(texts_to_families, families_to_texts),
        # Avec une valeur par défaut, la marche arrière peut recréer la colonne texte sur une table qui contient déjà des styles
        migrations.AlterField(model_name='style', name='family', field=models.CharField(blank=True, default='', max_length=60)),
        migrations.RemoveField(model_name='style', name='family'),
        migrations.RenameField(model_name='style', old_name='family_ref', new_name='family'),
        migrations.AlterField(
            model_name='style', name='family',
            field=models.ForeignKey(
                blank=True, help_text='Regroupe des styles comparables dans les statistiques. Vide : style à valider.', null=True,
                on_delete=django.db.models.deletion.PROTECT, related_name='styles', to='app.stylefamily', verbose_name='Famille',
            ),
        ),
        migrations.AlterModelOptions(name='style', options={'ordering': ['family', 'name'], 'verbose_name': 'Style de bière', 'verbose_name_plural': 'Styles de bière'}),
        migrations.AddConstraint(
            model_name='style',
            constraint=models.CheckConstraint(condition=models.Q(('is_official', False), ('family__isnull', False), _connector='OR'), name='official_style_has_a_family'),
        ),
    ]
