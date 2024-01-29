from django.urls import path, include
from rest_framework.urlpatterns import format_suffix_patterns
from gene2phenotype_app import views

def perform_create(self, serializer):
    serializer.save(owner=self.request.user)

# specify URL Path for rest_framework
urlpatterns = [
    path('gene2phenotype/api/panel/', views.PanelList.as_view(), name="list_panels"),
    path('gene2phenotype/api/panel/<str:name>', views.PanelDetail.as_view(), name="panel_details"),
    path('gene2phenotype/api/panel/<str:name>/stats', views.PanelStats.as_view(), name="panel_stats"),
    path('gene2phenotype/api/panel/<str:name>/records_summary', views.PanelRecordsSummary.as_view(), name="panel_summary"),
    path('gene2phenotype/api/users/', views.UserList.as_view(), name="list_users"),
    path('gene2phenotype/api/attrib/', views.AttribTypeList.as_view(), name="list_attrib_type"),
    path('gene2phenotype/api/attrib/<str:code>', views.AttribList.as_view(), name="list_attribs_by_type"),
    path('gene2phenotype/api/lgd/<str:stable_id>/', views.LocusGenotypeDiseaseDetail.as_view(), name="lgd"),
]

urlpatterns = format_suffix_patterns(urlpatterns)

urlpatterns += [
    path('api-auth/', include('rest_framework.urls'))
]