"""Section « Ma carte » du rapport d'un bar : la carte déclarée par le gérant comparée à ce que les membres boivent, notent, paient et souhaitent.

Quatre questions : que vaut ma carte (notes, composition) ? mes prix sont-ils dans la norme (prix payés par les membres, ramenés à mon format) ?
qu'est-ce qui se boit autour de moi sans être chez moi ? que veulent les membres que je ne sers pas ? Tout repose sur MIN_GROUP_SIZE : un chiffre
tiré de moins de 3 dégustateurs distincts n'est pas affiché.
"""
from collections import defaultdict
from statistics import mean

from django.db.models import Avg, Count, Q
from django.utils import timezone

from ...domain.styles import split_styles
from ...models import Beer, BeerUser, Drinks
from .blocks import Chart, Insight, Kpi, Table
from .formatting import euros, fr
from .privacy import MIN_GROUP_SIZE, is_publishable
from .profiles import FORMAT_LABELS, FORMAT_LITRES

HIDDEN = f'< {MIN_GROUP_SIZE}'
STALE_DAYS = 90
TOP = 10
PRICE_GAP_NOISE = 3  # écart de prix (en %) en dessous duquel on parle de « même niveau »


def _community_notes(ctx, beer_ids):
    """{bière: (note moyenne, dégustateurs qui ont noté)} sur la période."""
    rows = (Drinks.objects.filter(beer_id__in=beer_ids, date__gte=ctx.period.start).values('beer')
            .annotate(raters=Count('drinker', distinct=True, filter=Q(note__isnull=False)), avg=Avg('note')))
    return {row['beer']: (row['avg'], row['raters']) for row in rows}


def _community_price_per_litre(ctx, beer_ids):
    """{bière: prix moyen payé au litre} pour les bières payées par au moins MIN_GROUP_SIZE membres distincts (format connu pour la conversion)."""
    rows = (Drinks.objects.filter(beer_id__in=beer_ids, date__gte=ctx.period.start, price__isnull=False).exclude(serving_format='')
            .values_list('beer', 'price', 'serving_format', 'drinker'))
    prices, drinkers = defaultdict(list), defaultdict(set)
    for beer, price, serving_format, drinker in rows:
        litres = FORMAT_LITRES.get(serving_format)
        if litres:
            prices[beer].append(float(price) / litres)
            drinkers[beer].add(drinker)
    return {beer: mean(values) for beer, values in prices.items() if is_publishable(len(drinkers[beer]))}


def _wishes(beer_ids):
    through = BeerUser.wishlist_beers.through
    return {row['beer']: row['n'] for row in through.objects.filter(beer_id__in=beer_ids).values('beer').annotate(n=Count('pk'))}


def _local(ctx):
    """{bière: (dégustations, dégustateurs distincts)} autour du bar sur la période."""
    rows = ctx.drinks.values('beer').annotate(n=Count('pk'), members=Count('drinker', distinct=True))
    return {row['beer']: (row['n'], row['members']) for row in rows}


def _equivalent_price(per_litre, serving_format):
    """Prix payé par les membres ramené au format servi au bar (None si l'un des deux manque)."""
    litres = FORMAT_LITRES.get(serving_format)
    return per_litre * litres if per_litre is not None and litres else None


def _menu_table(ctx, entries, notes, ppl, wishes, local):
    rows, gaps, rated = [], [], []
    for entry in entries:
        note, raters = notes.get(entry.beer_id, (None, 0))
        note_ok = note is not None and is_publishable(raters)
        if note_ok:
            rated.append(note)
        equivalent = _equivalent_price(ppl.get(entry.beer_id), entry.serving_format)
        own = float(entry.price) if entry.price is not None else None
        gap = (own - equivalent) / equivalent * 100 if own is not None and equivalent else None
        if gap is not None:
            gaps.append(gap)
        n, members = local.get(entry.beer_id, (0, 0))
        around = (n if is_publishable(members) else HIDDEN) if ctx.publishable else '—'
        rows.append([
            entry.beer.name, entry.beer.brewery.name,
            euros(own) + (f' ({FORMAT_LABELS.get(entry.serving_format, "").split(" ")[0].lower()})' if entry.serving_format else '') if own is not None else '—',
            euros(equivalent) if equivalent else '—',
            f'{fr(round(gap), signed=True)} %' if gap is not None else '—',
            fr(round(note, 1), 1) if note_ok else '—', around, wishes.get(entry.beer_id, 0),
        ])
    table = Table('menu-beers', 'Ma carte', ['Bière', 'Brasserie', 'Votre prix', 'Prix payé (même format)', 'Écart', 'Note', 'Bue autour du bar', 'Souhaits'], rows,
                  subtitle='Prix payé : moyenne des prix déclarés par les membres pour cette bière, ramenée à votre format. Note et prix : au moins '
                           f'{MIN_GROUP_SIZE} membres. Souhaits : membres qui l\'ont mise en « à goûter ».')
    return table, rated, gaps


def _composition(entries):
    counts = defaultdict(int)
    for entry in entries:
        counts[entry.beer.style_family or 'Autre'] += 1
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return Chart('menu-families', 'Composition de la carte', 'donut', [name for name, _ in ordered], [{'name': 'Bières', 'data': [n for _, n in ordered]}],
                 subtitle='Bières de la carte par famille de styles')


def _missing_local(ctx, menu_ids, local):
    """Bières bues par au moins MIN_GROUP_SIZE membres autour du bar mais absentes de la carte."""
    wanted = [beer for beer, (_n, members) in local.items() if beer not in menu_ids and is_publishable(members)]
    if not wanted:
        return Table('menu-missing-local', 'Bues autour de votre bar, absentes de votre carte', ['Bière', 'Brasserie', 'Dégustateurs', 'Note'], [],
                     subtitle='Aucune bière absente de votre carte n\'est bue par assez de membres autour de vous')
    rows = (ctx.drinks.filter(beer_id__in=wanted).values('beer__name', 'beer__brewery__name', 'beer')
            .annotate(members=Count('drinker', distinct=True), avg=Avg('note')).order_by('-members', 'beer__name')[:TOP])
    return Table('menu-missing-local', 'Bues autour de votre bar, absentes de votre carte', ['Bière', 'Brasserie', 'Dégustateurs', 'Note'],
                 [[r['beer__name'], r['beer__brewery__name'], r['members'], fr(round(r['avg'], 1), 1) if r['avg'] is not None else '—'] for r in rows],
                 subtitle='Ce que vos propres clients boivent ailleurs ou à emporter : de bonnes candidates pour la carte')


def _missing_wished(menu_ids):
    """Bières les plus souhaitées sur Pokebeer (au moins MIN_GROUP_SIZE membres) que le bar ne sert pas."""
    wished = (Beer.objects.filter(is_deleted=False).exclude(pk__in=menu_ids).annotate(w=Count('wishlisted_by')).filter(w__gte=MIN_GROUP_SIZE)
              .select_related('brewery').order_by('-w', 'name')[:TOP])
    return Table('menu-missing-wished', 'Très souhaitées, absentes de votre carte', ['Bière', 'Brasserie', 'Style', 'Souhaits'],
                 [[beer.name, beer.brewery.name, beer.style or '—', beer.w] for beer in wished],
                 subtitle='Les bières que le plus de membres veulent goûter : un argument pour attirer du monde')


def _missing_styles(ctx, entries):
    """Styles bus autour du bar (au moins MIN_GROUP_SIZE dégustateurs distincts) dont aucune bière n'est à la carte."""
    served = {style.lower() for entry in entries for style in split_styles(entry.beer.style)}
    counts, drinkers = ctx.local_styles
    rows = [[style, count] for style, count in counts.most_common() if style.lower() not in served and is_publishable(len(drinkers[style]))]
    return Table('menu-missing-styles', 'Styles demandés autour de vous, absents de la carte', ['Style', 'Dégustations autour du bar'], rows[:TOP],
                 subtitle='Styles que vos clients boivent et que vous ne servez pas')


def _insights(ctx, entries, rated, gaps, missing_local, missing_wished, missing_styles):
    styles = {style for entry in entries for style in split_styles(entry.beer.style)}
    out = [Insight(f"Votre carte compte {len(entries)} bière{'s' if len(entries) > 1 else ''}" + (f" de {len(styles)} style{'s' if len(styles) > 1 else ''}." if styles else "."))]
    last = max(entry.added_at for entry in entries)
    age = (ctx.period.today - timezone.localtime(last).date()).days
    if age >= STALE_DAYS:
        out.append(Insight(f"Votre carte n'a pas été complétée depuis {age} jours : les statistiques supposent qu'elle est à jour.", "warn"))
    if rated:
        average = mean(rated)
        community = ctx.community_average
        suffix = f" (moyenne de la communauté : {fr(round(community, 1), 1)})" if community is not None else ''
        tone = 'good' if community is not None and average >= community + 0.3 else 'neutral'
        out.append(Insight(f"Vos bières sont notées {fr(round(average, 1), 1)}/10 en moyenne{suffix}.", tone))
    if gaps:
        gap = mean(gaps)
        if abs(gap) < PRICE_GAP_NOISE:
            out.append(Insight("Vos prix sont au niveau de ce que les membres déclarent payer pour les mêmes bières."))
        else:
            side = "au-dessus" if gap > 0 else "en dessous"
            out.append(Insight(f"Vos prix sont en moyenne {fr(round(abs(gap)))} % {side} de ce que les membres déclarent payer pour les mêmes bières.", "neutral"))
    if missing_local.rows:
        names = ', '.join(row[0] for row in missing_local.rows[:3])
        out.append(Insight(f"Des bières bues autour de votre bar ne sont pas à votre carte : {names}.", "good"))
    if missing_wished.rows:
        out.append(Insight(f"{missing_wished.rows[0][0]} est mise en « à goûter » par {missing_wished.rows[0][3]} membres et n'est pas à votre carte.", "good"))
    if missing_styles.rows:
        out.append(Insight(f"Vos clients boivent du {missing_styles.rows[0][0]} ({missing_styles.rows[0][1]} dégustations) : aucune bière de ce style à la carte.", "good"))
    return out


def build(ctx):
    """Blocs de la section « Ma carte » ; liste vide si le bar n'a pas encore déclaré de carte (le gabarit propose alors de la saisir)."""
    entries = ctx.menu_entries
    if not entries:
        return []
    ids = [entry.beer_id for entry in entries]
    menu_ids = set(ids)
    notes, ppl, wishes = _community_notes(ctx, ids), _community_price_per_litre(ctx, ids), _wishes(ids)
    local = _local(ctx) if ctx.publishable else {}
    table, rated, gaps = _menu_table(ctx, entries, notes, ppl, wishes, local)
    missing_local = _missing_local(ctx, menu_ids, local) if ctx.publishable else Table('menu-missing-local', 'Bues autour de votre bar, absentes de votre carte', ['Bière'], [])
    missing_wished = _missing_wished(menu_ids)
    missing_styles = _missing_styles(ctx, entries) if ctx.publishable else Table('menu-missing-styles', 'Styles demandés autour de vous, absents de la carte', ['Style'], [])
    prices = [float(entry.price) for entry in entries if entry.price is not None]
    blocks = [
        Kpi('Bières à la carte', len(entries), hint=f'{len({s for e in entries for s in split_styles(e.beer.style)})} styles'),
        Kpi('Prix moyen à la carte', euros(mean(prices)) if prices else '—', hint=f'prix renseigné pour {len(prices)} bière{"s" if len(prices) > 1 else ""} sur {len(entries)}'),
        Kpi('Note moyenne de la carte', f'{fr(round(mean(rated), 1), 1)}/10' if rated else '—', hint='moyenne des notes des membres sur vos bières'),
    ]
    blocks += [_composition(entries), table, missing_local, missing_wished, missing_styles]
    return [*_insights(ctx, entries, rated, gaps, missing_local, missing_wished, missing_styles), *blocks]
