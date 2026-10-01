import pytest
from django.urls import reverse

from app.models import CustomNotebook
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db

NOTEBOOK_LIMIT = 50


def fill_notebooks(user, count):
    CustomNotebook.objects.bulk_create([CustomNotebook(user=user, title=f"Carnet {i}") for i in range(count)])


class TestNotebookPages:
    def test_overview_lists_only_own_content(self, auth_client, user, other_user):
        mine = f.make_notebook(user)
        f.make_notebook(other_user)
        f.make_beer(added_by=user, is_deleted=True)
        context = auth_client.get(reverse("notebook")).context
        assert list(context["custom_notebooks"]) == [mine]
        assert len(context["my_deleted_beers"]) == 1

    def test_active_tab_comes_from_query_string(self, auth_client):
        assert auth_client.get(reverse("notebook"), {"tab": "ajouts"}).context["active_tab"] == "ajouts"

    def test_detail_shows_only_the_notebook_drinks(self, auth_client, user):
        inside, outside = f.make_drink(user, f.make_beer(style="Stout, IPA")), f.make_drink(user)
        notebook = f.make_notebook(user, drinks=[inside])
        context = auth_client.get(reverse("notebook_detail", args=[notebook.slug])).context
        assert list(context["my_drinks"]) == [inside]
        assert context["notebook_drink_slugs"] == [inside.slug]
        assert context["styles"] == ["IPA", "Stout"]

    def test_all_drinks_view_paginates_to_ten(self, auth_client, user):
        for _ in range(11):
            f.make_drink(user)
        assert len(auth_client.get(reverse("notebook_all")).context["my_drinks"]) == 10

    @pytest.mark.parametrize("name, method", [("notebook_detail", "get"), ("edit_custom_notebook", "post"), ("delete_custom_notebook", "post")])
    def test_other_users_notebooks_are_404(self, auth_client, other_user, name, method):
        notebook = f.make_notebook(other_user)
        assert getattr(auth_client, method)(reverse(name, args=[notebook.slug]), {"title": "Pirate"}).status_code == 404
        assert CustomNotebook.objects.get(pk=notebook.pk).title != "Pirate"


class TestCreateNotebook:
    URL = reverse("create_custom_notebook")

    def test_creates_with_own_drinks_only(self, auth_client, user, other_user):
        mine, foreign = f.make_drink(user), f.make_drink(other_user)
        assert_redirects(auth_client.post(self.URL, {"title": "Favoris", "drinks": [mine.slug, foreign.slug]}), reverse("notebook"))
        assert list(CustomNotebook.objects.get(user=user).drinks.all()) == [mine]

    def test_title_is_required(self, auth_client):
        auth_client.post(self.URL, {"title": ""})
        assert not CustomNotebook.objects.exists()

    def test_last_notebook_below_the_limit_is_accepted(self, auth_client, user):
        fill_notebooks(user, NOTEBOOK_LIMIT - 1)
        auth_client.post(self.URL, {"title": "Dernier"})
        assert user.custom_notebooks.count() == NOTEBOOK_LIMIT

    def test_limit_is_enforced(self, auth_client, user):
        fill_notebooks(user, NOTEBOOK_LIMIT)
        auth_client.post(self.URL, {"title": "De trop"})
        assert user.custom_notebooks.count() == NOTEBOOK_LIMIT

    def test_limit_is_per_user(self, auth_client, user, other_user):
        fill_notebooks(other_user, NOTEBOOK_LIMIT)
        auth_client.post(self.URL, {"title": "Mien"})
        assert user.custom_notebooks.count() == 1

    def test_too_long_title_is_refused_with_an_explanation(self, auth_client):
        response = auth_client.post(self.URL, {"title": "x" * 151})
        assert_redirects(response, reverse("notebook"))
        assert not CustomNotebook.objects.exists()
        assert any(m.startswith("Le carnet n'a pas pu être créé : Titre :") for m in messages_of(response))

    def test_title_of_max_length_is_accepted(self, auth_client, user):
        auth_client.post(self.URL, {"title": "x" * 150})
        assert user.custom_notebooks.get().title == "x" * 150

    def test_unknown_drink_slugs_are_ignored(self, auth_client, user):
        drink = f.make_drink(user)
        auth_client.post(self.URL, {"title": "Mixte", "drinks": [drink.slug, "abc", "-1"]})
        assert list(user.custom_notebooks.get().drinks.all()) == [drink]


class TestEditAndDeleteNotebook:
    def test_edit_replaces_title_and_drinks(self, auth_client, user, other_user):
        old, new, foreign = f.make_drink(user), f.make_drink(user), f.make_drink(other_user)
        notebook = f.make_notebook(user, drinks=[old])

        auth_client.post(reverse("edit_custom_notebook", args=[notebook.slug]), {"title": "Renommé", "drinks": [new.slug, foreign.slug]})

        notebook.refresh_from_db()
        assert notebook.title == "Renommé"
        assert list(notebook.drinks.all()) == [new]

    def test_edit_without_title_changes_nothing(self, auth_client, user):
        notebook = f.make_notebook(user, title="Garde", drinks=[f.make_drink(user)])
        auth_client.post(reverse("edit_custom_notebook", args=[notebook.slug]), {"title": ""})
        notebook.refresh_from_db()
        assert (notebook.title, notebook.drinks.count()) == ("Garde", 1)

    def test_too_long_title_on_edit_changes_nothing_and_explains(self, auth_client, user):
        notebook = f.make_notebook(user, title="Garde", drinks=[f.make_drink(user)])
        response = auth_client.post(reverse("edit_custom_notebook", args=[notebook.slug]), {"title": "x" * 151, "drinks": []})
        assert_redirects(response, reverse("notebook_detail", args=[notebook.slug]))
        notebook.refresh_from_db()
        assert (notebook.title, notebook.drinks.count()) == ("Garde", 1)
        assert any(m.startswith("Le carnet n'a pas pu être modifié : Titre :") for m in messages_of(response))

    def test_unknown_drink_slugs_on_edit_are_ignored(self, auth_client, user):
        drink = f.make_drink(user)
        notebook = f.make_notebook(user)
        auth_client.post(reverse("edit_custom_notebook", args=[notebook.slug]), {"title": "Ok", "drinks": [drink.slug, "abc"]})
        assert list(notebook.drinks.all()) == [drink]

    def test_delete_keeps_the_drinks(self, auth_client, user):
        drink = f.make_drink(user)
        notebook = f.make_notebook(user, drinks=[drink])
        auth_client.post(reverse("delete_custom_notebook", args=[notebook.slug]))
        assert not CustomNotebook.objects.exists()
        assert type(drink).objects.filter(pk=drink.pk).exists()
