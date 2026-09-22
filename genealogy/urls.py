from django.urls import path

from . import views

urlpatterns = [
    path("", views.map_view, name="map"),
    path("api/graph/", views.graph_data, name="graph-data"),
    path("api/people/<int:person_id>/", views.person_detail, name="person-detail"),
    path("api/people/add/", views.add_person, name="add-person"),
]
