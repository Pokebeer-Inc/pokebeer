from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import BeerUser, Beer, Brewery, Drinks
from django.utils.text import slugify

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = BeerUser
        # Fields you want the user to fill in
        fields = ['username', 'email']

    def clean_email(self):
        # Add custom validation to ensure email is unique
        email = self.cleaned_data.get('email')
        if BeerUser.objects.filter(email=email).exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email

class UserLoginForm(AuthenticationForm):
    # Built-in AuthenticationForm handles username/password checks securely
    pass

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = BeerUser
        fields = ['username', 'email', 'bio']
        labels = {
            'username': "Nom d'utilisateur",
            'email': "Adresse Email",
            'bio': "Ma Biographie"
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Parlez-nous de vos goûts brassicoles...'})
        }

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 10px;'
            })

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # On vérifie si l'email existe déjà chez un AUTRE utilisateur (exclure self.instance)
        if BeerUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un autre membre.")
        return email

class BeerForm(forms.ModelForm):
    brewery_name = forms.CharField(
        label='Brasserie',
        help_text="Tapez le nom. Si elle n'existe pas, elle sera créée.",
        widget=forms.TextInput(attrs={'autocomplete': 'off'})
    )

    class Meta:
        model = Beer
        fields = ['name', 'brewery_name', 'style', 'description', 'bitterness', 'degree']
        labels = {
            'name': 'Nom de la bière',
            'description': 'Description',
            'bitterness': 'Amertume (IBU)',
            'degree': 'Degré d\'alcool (%)',
            'style': 'Style de bière',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'name': forms.TextInput(attrs={'autocomplete': 'off'})
        }

    def __init__(self, *args, **kwargs):
        super(BeerForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;'
            })

    def save(self, user=None, commit=True):
        beer = super(BeerForm, self).save(commit=False)
        b_name = self.cleaned_data['brewery_name']
        brewery, created = Brewery.objects.get_or_create(
            name__iexact=b_name,
            defaults={'name': b_name, 'city': 'Inconnue', 'description': 'Ajoutée automatiquement'}
        )
        beer.brewery_id = brewery
        
        if user:
            beer.added_by = user
            
        if commit:
            beer.save()
        return beer
    
    def clean_name(self):
        """Bouclier anti-doublon insensible à la casse, espaces, et accents"""
        name = self.cleaned_data.get('name')
        if name:
            # On transforme le nom tapé en slug (ex: "Pünk I.P.A " devient "punk-ipa")
            normalized_name = slugify(name)
            
            # On cherche si une bière avec ce même slug exact existe déjà
            existing_beer = Beer.objects.filter(slug=normalized_name).first()
            if existing_beer:
                raise forms.ValidationError(f"Cette bière existe déjà sous le nom '{existing_beer.name}'")
        return name
    
class DrinkForm(forms.ModelForm):
    class Meta:
        model = Drinks
        fields = ['date', 'note', 'comment']
        labels = {
            'date': 'Date de dégustation',
            'note': 'Note (sur 10)',
            'comment': 'Mon avis personnel'
        }
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Votre expérience, vos impressions en toute subjectivité...', 'class': 'textarea textarea-bordered w-full'}),
            'note': forms.NumberInput(attrs={'min': 0, 'max': 10}),
        }

    def __init__(self, *args, **kwargs):
        super(DrinkForm, self).__init__(*args, **kwargs)
        # Style uniforme pour faire "Pro"
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control',
                'style': 'width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px;'
            })