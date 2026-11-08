from django.contrib.auth import views as auth_views
from django.urls import path

from . import accounts, onboarding, views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("invite/<str:code>/", accounts.register, name="register"),
    path("account/", accounts.account, name="account"),
    path("start/self/", onboarding.start_self, name="start-self"),
    path("start/gedcom/", onboarding.start_gedcom, name="start-gedcom"),
    path("", views.tree_page, name="tree"),
    path("people/<str:code>/", views.person_page, name="person-page"),
    path("people/<str:code>/materials/", views.add_material_view, name="person-add-material"),
    path("tree.svg", views.tree_svg, name="tree-svg"),
    path("api/tree/", views.tree_api, name="tree-api"),
    path("api/people/<int:pk>/", views.person_api, name="person-api"),
    path("api/people/<int:pk>/add/", views.add_relative_api, name="person-add"),
]
