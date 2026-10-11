"""Intégrité des données : une note par membre et par bière, un signalement = une cible, trophées rangés par identifiant stable, index."""
from django.db import migrations, models
from django.db.models import Count

ACHIEVEMENT_SLUGS = {
    "Poche": "poche", "Juge": "juge", "Communautaire": "communaute", "Voyageur": "voyageur", "Mauvaise cuite": "bad_trip",
    "César": "cesar", "Irlandais": "irlandais", "Copain de Gaétan": "picon", "Ours doré": "ours",
}


def names_to_slugs(apps, schema_editor):
    for model in (apps.get_model('app', 'UserAchievementState'), apps.get_model('app', 'Notification')):
        for name, slug in ACHIEVEMENT_SLUGS.items():
            model.objects.filter(achievement_slug=name).update(achievement_slug=slug)


def slugs_to_names(apps, schema_editor):
    for model in (apps.get_model('app', 'UserAchievementState'), apps.get_model('app', 'Notification')):
        for name, slug in ACHIEVEMENT_SLUGS.items():
            model.objects.filter(achievement_slug=slug).update(achievement_slug=name)


def merge_duplicate_tastings(apps, schema_editor):
    """Si un membre a noté deux fois la même bière (double envoi), on garde la dernière note et on lui rattache ce qui pointait vers les autres :
    carnets, lieux, réactions et signalements. Aucun contenu rattaché n'est perdu."""
    Drinks = apps.get_model('app', 'Drinks')
    DrinkReaction = apps.get_model('app', 'DrinkReaction')
    Report = apps.get_model('app', 'Report')
    duplicates = Drinks.objects.values('drinker_id', 'beer_id').annotate(n=Count('id')).filter(n__gt=1)
    for group in duplicates:
        rows = list(Drinks.objects.filter(drinker_id=group['drinker_id'], beer_id=group['beer_id']).order_by('-date', '-id'))
        keep, extras = rows[0], rows[1:]
        for extra in extras:
            for notebook in extra.notebooks.all():
                notebook.drinks.add(keep)
            for spot in extra.spots.all():
                spot.drinks.add(keep)
            for reaction in DrinkReaction.objects.filter(drink=extra):
                if DrinkReaction.objects.filter(drink=keep, user_id=reaction.user_id).exists():
                    reaction.delete()
                else:
                    reaction.drink = keep
                    reaction.save(update_fields=['drink'])
            Report.objects.filter(reported_drink=extra).update(reported_drink=keep)
            extra.delete()
    # PostgreSQL refuse de modifier une table dont les vérifications de clés étrangères (différées) sont encore en attente
    schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def refuse_reports_without_one_target(apps, schema_editor):
    """Le signalement doit viser exactement une cible : s'il en existe qui n'en visent aucune ou plusieurs, on s'arrête en les nommant
    plutôt que de les supprimer (c'est à l'équipe de décider)."""
    Report = apps.get_model('app', 'Report')
    bad = []
    for report in Report.objects.all().only('id', 'reported_beer_id', 'reported_drink_id', 'reported_user_id', 'reported_brewery_id'):
        targets = [report.reported_beer_id, report.reported_drink_id, report.reported_user_id, report.reported_brewery_id]
        if sum(target is not None for target in targets) != 1:
            bad.append(report.pk)
    if bad:
        raise RuntimeError(f"Signalements sans cible unique (ids {bad}) : corrigez-les dans l'administration avant de relancer la migration.")


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0085_moderation_suggestions'),
    ]

    operations = [
        # Trophées : identifiant stable à la place du nom affiché
        migrations.RenameField('userachievementstate', 'achievement_name', 'achievement_slug'),
        migrations.RenameField('notification', 'achievement_name', 'achievement_slug'),
        migrations.RunPython(names_to_slugs, slugs_to_names),

        # Une note par membre et par bière
        migrations.RunPython(merge_duplicate_tastings, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='drinks',
            constraint=models.UniqueConstraint(fields=('drinker_id', 'beer_id'), name='unique_drink_per_member_and_beer', violation_error_message='Vous avez déjà noté cette bière.'),
        ),

        # Un signalement = une cible
        migrations.RunPython(refuse_reports_without_one_target, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='report',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(reported_beer__isnull=False, reported_drink__isnull=True, reported_user__isnull=True, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=False, reported_user__isnull=True, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=True, reported_user__isnull=False, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=True, reported_user__isnull=True, reported_brewery__isnull=False)
                ),
                name='report_exactly_one_target',
                violation_error_message='Choisissez exactement une cible : bière, note, membre ou brasserie.',
            ),
        ),

        # Index
        migrations.AddIndex(model_name='report', index=models.Index(fields=['status'], name='report_status_idx')),
        migrations.AddIndex(model_name='throttlehit', index=models.Index(fields=['created_at'], name='throttle_created_idx')),
        migrations.AddIndex(model_name='notification', index=models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_recipient_unread_idx')),
        migrations.AddIndex(model_name='beer', index=models.Index(condition=models.Q(('is_deleted', False)), fields=['id'], name='beer_active_idx')),
    ]
