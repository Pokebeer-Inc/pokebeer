"""Les clés étrangères se nomment comme ce qu'elles désignent : Drinks.drinker / Drinks.beer / Beer.brewery (et non `drinker_id`, `beer_id`,
`brewery_id`, qui donnaient les attributs `beer_id_id`…). L'identifiant brut reste disponible sous `beer_id`, comme partout dans Django.

Les colonnes sont renommées (`beer_id_id` -> `beer_id`) sans toucher aux données. Les index et contraintes qui citent ces champs sont
retirés puis recréés avec les nouveaux noms."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0087_rename_chatusage_to_quotausage'),
    ]

    operations = [
        migrations.RemoveIndex(model_name='drinks', name='drinks_drinker_date_idx'),
        migrations.RemoveConstraint(model_name='drinks', name='unique_drink_per_member_and_beer'),
        migrations.RemoveConstraint(model_name='beer', name='unique_active_beer_name_per_brewery'),

        migrations.RenameField(model_name='drinks', old_name='drinker_id', new_name='drinker'),
        migrations.RenameField(model_name='drinks', old_name='beer_id', new_name='beer'),
        migrations.RenameField(model_name='beer', old_name='brewery_id', new_name='brewery'),

        migrations.AddIndex(model_name='drinks', index=models.Index(fields=['drinker', '-date'], name='drinks_drinker_date_idx')),
        migrations.AddConstraint(
            model_name='drinks',
            constraint=models.UniqueConstraint(fields=('drinker', 'beer'), name='unique_drink_per_member_and_beer', violation_error_message='Vous avez déjà noté cette bière.'),
        ),
        migrations.AddConstraint(
            model_name='beer',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_deleted', False)), fields=('brewery', 'name'), name='unique_active_beer_name_per_brewery',
                violation_error_message='Cette brasserie a déjà une bière de ce nom.'),
        ),
    ]
