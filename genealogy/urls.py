from django.urls import path

from . import views

urlpatterns = [
    path("", views.tree_page, name="tree"),
    path("people/<str:code>/", views.person_page, name="person-page"),
    path("tree.svg", views.tree_svg, name="tree-svg"),
    path("api/tree/", views.tree_api, name="tree-api"),
    path("api/people/<int:pk>/", views.person_api, name="person-api"),
    path("api/people/<int:pk>/add/", views.add_relative_api, name="person-add"),
]
