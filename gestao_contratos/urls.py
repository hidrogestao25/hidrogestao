from django.urls import path
from . import views
from .views import ContratoCreateView, ClienteCreateView, FornecedorCreateView, ContratoFornecedorCreateView

urlpatterns = [
    path('contratos/', views.lista_contratos, name='lista_contratos'),
    path('contratos/novo/', ContratoCreateView.as_view(), name='novo_contrato'),
    path('contratos/<int:pk>/', views.contrato_cliente_detalhe, name='contrato_cliente_detalhe'),

    path('contratos_fornecedores', views.lista_contratos_fornecedor, name='lista_contratos_fornecedores'),
    path('contratos_fornecedores/novo', ContratoFornecedorCreateView.as_view(), name='novo_contrato_fornecedor'),
    path('contratos_fornecedores/<int:pk>/', views.contrato_fornecedor_detalhe, name='contrato_fornecedor_detalhe'),

    path('clientes/', views.lista_clientes, name='lista_clientes'),
    path('clientes/novo/', ClienteCreateView.as_view(), name='novo_cliente'),
    path('clientes/<int:pk>/', views.cliente_detalhe, name='cliente_detalhe'),

    path('fornecedores/', views.lista_fornecedores, name='lista_fornecedores'),
    path('fornecedores/novo/', FornecedorCreateView.as_view(), name='novo_fornecedor'),
    path('fornecedores/<int:pk>/', views.fornecedor_detalhe, name='fornecedor_detalhe'),
    path('fornecedores/solicitar/', views.nova_solicitacao_prospeccao, name='nova_solicitacao_prospeccao'),
    path('fornecedores/solicitacoes/', views.lista_solicitacoes, name='lista_solicitacoes'),
    path('fornecedores/solicitacoes/<int:pk>/<str:acao>/', views.aprovar_solicitacao, name='aprovar_solicitacao'),
    path('fornecedores/solicitacoes/triagem/<int:pk>/', views.triagem_fornecedores, name='triagem_fornecedores'),
    path('fornecedores/solicitacoes//nenhum<int:pk>/', views.nenhum_fornecedor_ideal, name='nenhum_fornecedor_ideal'),
    path('fornecedores/solicitacoes/<int:pk>', views.detalhes_triagem_fornecedores, name='detalhes_triagem_fornecedores'),

    path('solicitacoes/<int:pk>/detalhes/', views.detalhes_solicitacao, name='detalhes_solicitacao'),
    path('solicitacoes/<int:pk>/propostas/', views.propostas_fornecedores, name='propostas_fornecedores'),
    path("solicitacao/<int:pk>/renegociar-valor/", views.renegociar_valor, name="renegociar_valor"),
    path("solicitacao/<int:pk>/renegociar-prazo/", views.renegociar_prazo, name="renegociar_prazo"),
    path("solicitacao/<int:pk>/nova-prospeccao/", views.nova_prospeccao, name="nova_prospeccao"),

    path('elaboracao_contrato/', views.elaboracao_contrato, name='elaboracao_contrato'),
    path('elaboracao_contrato/<int:solicitacao_id>/cadastrar/', views.cadastrar_contrato, name='cadastrar_contrato'),
    path('detalhes_contrato/<int:pk>/', views.detalhes_contrato, name='detalhes_contrato'),


]
