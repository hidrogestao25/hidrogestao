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
    path('contratos_fornecedores/<int:pk>/editar/', views.contrato_fornecedor_editar, name='contrato_fornecedor_editar'),

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
    path('solicitacoes/<int:pk>/aprovar_fornecedor/', views.aprovar_fornecedor_gerente, name='aprovar_fornecedor_gerente'),
    path('fornecedores/solicitacoes//nenhum<int:pk>/', views.nenhum_fornecedor_ideal, name='nenhum_fornecedor_ideal'),
    path('fornecedores/solicitacoes/<int:pk>', views.detalhes_triagem_fornecedores, name='detalhes_triagem_fornecedores'),

    path('solicitacoes/<int:pk>/detalhes/', views.detalhes_solicitacao, name='detalhes_solicitacao'),
    path("solicitacao/<int:pk>/evento/novo/", views.cadastrar_evento, name="cadastrar_evento"),
    path("contrato/<int:pk>/evento/novo/", views.cadastrar_evento_contrato, name="cadastrar_evento_contrato"),
    path('solicitacoes/<int:pk>/propostas/', views.propostas_fornecedores, name='propostas_fornecedores'),
    path("solicitacao/<int:pk>/renegociar-valor/", views.renegociar_valor, name="renegociar_valor"),
    path("solicitacao/<int:pk>/renegociar-prazo/", views.renegociar_prazo, name="renegociar_prazo"),
    path("solicitacao/<int:pk>/nova-prospeccao/", views.nova_prospeccao, name="nova_prospeccao"),

    path('elaboracao_contrato/', views.elaboracao_contrato, name='elaboracao_contrato'),
    path('elaboracao_contrato/<int:solicitacao_id>/cadastrar/', views.cadastrar_contrato, name='cadastrar_contrato'),
    path('detalhes_contrato/<int:pk>/', views.detalhes_contrato, name='detalhes_contrato'),

    path("solicitacoes/<int:pk>/inserir-minuta-bm/", views.inserir_minuta_bm, name="inserir_minuta_bm"),

    path("bm/<int:pk>/detalhe/", views.detalhe_bm, name="detalhe_bm"),
    path("bm/<int:pk>/aprovar/<str:papel>/", views.aprovar_bm, name="aprovar_bm"),
    path("bm/<int:pk>/reprovar/<str:papel>/", views.reprovar_bm, name="reprovar_bm"),
    path('bms/<int:bm_id>/avaliar/', views.avaliar_bm, name='avaliar_bm'),

    path("evento/<int:pk>/editar/", views.editar_evento, name="editar_evento"),
    path("evento_contrato/<int:pk>/editar/", views.editar_evento_contrato, name="editar_evento_contrato"),
    path("evento/<int:pk>/excluir/", views.excluir_evento, name="excluir_evento"),
    path("evento_contrato/<int:pk>/excluir/", views.excluir_evento_contrato, name="excluir_evento_contrato"),
    path("evento/<int:pk>/registrar-entrega/", views.registrar_entrega, name="registrar_entrega"),
    path("contrato/<int:contrato_id>/evento/<int:evento_id>/bm/novo/", views.cadastrar_bm, name="cadastrar_bm"),
    path('evento/<int:evento_id>/detalhes/', views.detalhes_entrega, name='detalhes_entrega'),

    path("previsao-pagamentos/", views.previsao_pagamentos, name="previsao_pagamentos"),
    path('previsao-pagamentos/exportar/', views.exportar_previsao_pagamentos_excel, name='exportar_previsao_pagamentos_excel'),

    path('download_bms_aprovados/', views.download_bms_aprovados, name='download_bms_aprovados'),

    path('ranking-fornecedores/', views.ranking_fornecedores, name='ranking_fornecedores'),
]
