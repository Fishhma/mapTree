"""Вход, выход, регистрация по приглашению, язык интерфейса и страница «Аккаунт».

Приглашение — одноразовая ссылка /invite/<код>/, которую администратор создаёт в
админке и отправляет человеку. По ней можно один раз зарегистрироваться; после
регистрации у человека появляется своё пустое древо. Без приглашения
зарегистрироваться нельзя.

Язык: до входа — по браузеру, переключатель /lang/<код>/ на страницах входа и
регистрации; при регистрации язык выбирается в форме, потом меняется в «Аккаунте».

Страница /account/: язык, смена логина и пароля, «удалить древо и начать заново»
(после этого снова открывается окно первого входа — можно загрузить GEDCOM)
и удаление учётной записи вместе с древом. Удаление защищено от случайного
нажатия: нужно ввести свой пароль и вписать подтверждение.
"""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .importer import clear_tree
from .models import FamilyTree, Invitation, Source, UserProfile

User = get_user_model()
LANGUAGE_CODES = [code for code, _name in settings.LANGUAGES]


def clear_phrase() -> str:
    return _("удалить древо")


# ---------- язык до входа ----------

@login_not_required
def set_language(request, code):
    """Переключатель RU · EN · CS: язык запоминается в cookie, страница открывается заново."""
    target = request.GET.get("next") or reverse("login")
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        target = reverse("login")
    response = HttpResponseRedirect(target)
    if code in LANGUAGE_CODES:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, code,
                            max_age=settings.LANGUAGE_COOKIE_AGE, samesite="Lax")
    return response


# ---------- регистрация ----------

class RegisterForm(UserCreationForm):
    language = forms.ChoiceField(label=gettext_lazy("Язык интерфейса"), choices=settings.LANGUAGES)
    field_order = ("language", "username", "password1", "password2")

    class Meta(UserCreationForm.Meta):
        fields = ("username",)
        labels = {"username": gettext_lazy("Логин")}


@login_not_required
def register(request, code):
    invitation = Invitation.objects.filter(code=code).first()
    if invitation is None or not invitation.is_usable:
        return render(request, "registration/invite_invalid.html", {"invitation": invitation}, status=404)
    if request.user.is_authenticated:
        return render(request, "registration/invite_invalid.html",
                      {"invitation": invitation, "signed_in": True}, status=400)
    form = RegisterForm(request.POST or None, initial={"language": translation.get_language()})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
            if not invitation.is_usable:          # пока заполняли форму, ссылку уже использовали
                return render(request, "registration/invite_invalid.html", {"invitation": invitation},
                              status=404)
            user = form.save()
            UserProfile.objects.create(user=user, language=form.cleaned_data["language"])
            FamilyTree.objects.create(owner=user)
            invitation.used_by, invitation.used_at = user, timezone.now()
            invitation.save(update_fields=["used_by", "used_at"])
        login(request, user)
        translation.activate(form.cleaned_data["language"])    # cookie обновит UserLanguageMiddleware
        return redirect("tree")
    return render(request, "registration/register.html", {"form": form, "invitation": invitation})


# ---------- страница «Аккаунт» ----------

def _password_field():
    return forms.CharField(label=gettext_lazy("Ваш пароль"), strip=False,
                           widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class LanguageForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("language",)
        labels = {"language": gettext_lazy("Язык интерфейса")}


class UsernameForm(forms.ModelForm):
    """Новый логин. Нынешний пароль — чтобы логин не сменил тот, кто сел за чужой компьютер."""
    password = _password_field()

    class Meta:
        model = User
        fields = ("username",)
        labels = {"username": gettext_lazy("Новый логин")}
        help_texts = {"username": ""}

    def __init__(self, user, *args, **kwargs):
        # Отдельная копия: форма меняет свой объект ещё до проверки, а шапка страницы
        # должна показывать нынешний логин, пока новый не сохранён.
        super().__init__(*args, instance=User.objects.get(pk=user.pk), **kwargs)
        self.old_username = user.username

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username == self.old_username:
            raise forms.ValidationError(_("Это и есть ваш нынешний логин."))
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.instance.check_password(password):
            raise forms.ValidationError(_("Неверный пароль."))
        return password


class ConfirmForm(forms.Form):
    """Подтверждение опасного действия: свой пароль и вписанная фраза."""
    password = _password_field()
    confirm = forms.CharField(label=gettext_lazy("Подтверждение"),
                              widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, user, phrase: str, *args, exact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.phrase, self.exact = user, phrase, exact
        self.fields["confirm"].label = _("Впишите «%(phrase)s»") % {"phrase": phrase}

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("Неверный пароль."))
        return password

    def clean_confirm(self):
        typed = self.cleaned_data["confirm"].strip()
        same = (typed == self.phrase if self.exact
                else " ".join(typed.split()).casefold() == self.phrase.casefold())
        if not same:
            raise forms.ValidationError(_("Нужно вписать «%(phrase)s».") % {"phrase": self.phrase})
        return typed


def can_delete_account(user) -> bool:
    """Последнего администратора удалить нельзя: иначе некому будет войти в админку."""
    if not user.is_superuser:
        return True
    return User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).exists()


def account(request):
    user = request.user
    tree = FamilyTree.of(user)
    action = request.POST.get("action") if request.method == "POST" else None

    def data(name):
        return request.POST if action == name else None

    # auto_id: у полей разных форм на одной странице должны быть разные id.
    language_form = LanguageForm(data("language"), instance=UserProfile.of(user), auto_id="language_%s")
    username_form = UsernameForm(user, data("username"), auto_id="login_%s")
    password_form = PasswordChangeForm(user, data("password"), auto_id="password_%s")
    password_form.fields["old_password"].widget.attrs.pop("autofocus", None)
    password_form.fields["new_password2"].help_text = ""
    clear_form = ConfirmForm(user, clear_phrase(), data("clear"), auto_id="clear_%s")
    delete_form = ConfirmForm(user, user.username, data("delete"), exact=True, auto_id="delete_%s")
    deletable = can_delete_account(user)

    if action == "language" and language_form.is_valid():
        profile = language_form.save()
        translation.activate(profile.language)                   # сообщение — уже на новом языке
        messages.success(request, _("Язык интерфейса изменён."), extra_tags="language")
        return redirect(reverse("account") + "#language")
    if action == "username" and username_form.is_valid():
        username_form.save()
        messages.success(request, _("Логин изменён. Теперь вы входите как «%(username)s».")
                         % {"username": username_form.instance.username}, extra_tags="login")
        return redirect(reverse("account") + "#login")
    if action == "password" and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)   # чтобы не выкинуло со страницы
        messages.success(request, _("Пароль изменён."), extra_tags="password")
        return redirect(reverse("account") + "#password")
    if action == "clear" and clear_form.is_valid():
        with transaction.atomic():
            clear_tree(tree)
        return redirect("tree")                                  # там откроется окно первого входа
    if action == "delete" and deletable and delete_form.is_valid():
        logout(request)
        with transaction.atomic():
            user.delete()                                        # древо, люди и материалы — следом
        return render(request, "registration/account_deleted.html")

    return render(request, "genealogy/account.html", {
        "tree": tree,
        "people": tree.people.count(),
        "materials": Source.objects.filter(tree=tree).count(),
        "language_form": language_form,
        "username_form": username_form,
        "password_form": password_form,
        "clear_form": clear_form,
        "delete_form": delete_form,
        "deletable": deletable,
        "danger_open": action in ("clear", "delete"),
    }, status=400 if action else 200)
