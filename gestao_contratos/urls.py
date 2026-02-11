from django.urls import path
from . import views
from .views import ContratoCreateView, ClienteCreateView, FornecedorCreateView, ContratoFornecedorCreateView, OSCreateView

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
    path('contrato/<int:pk>/detalhes/', views.detalhes_solicitacao_contrato, name='detalhes_solicitacao_contrato'),
    path("solicitacao/<int:pk>/evento/novo/", views.cadastrar_evento, name="cadastrar_evento"),
    path("solicitacao_contrato/<int:pk>/evento/novo/", views.cadastrar_evento_solicitacao, name="cadastrar_evento_solicitacao"),
    path("contrato/<int:pk>/evento/novo/", views.cadastrar_evento_contrato, name="cadastrar_evento_contrato"),
    path('solicitacoes/<int:pk>/propostas/', views.propostas_fornecedores, name='propostas_fornecedores'),
    path("solicitacao/<int:pk>/renegociar-valor/", views.renegociar_valor, name="renegociar_valor"),
    path("solicitacao/<int:pk>/renegociar-prazo/", views.renegociar_prazo, name="renegociar_prazo"),
    path("solicitacao/<int:pk>/nova-prospeccao/", views.nova_prospeccao, name="nova_prospeccao"),
    path('fornecedores/solicitar_contratacao/', views.nova_solicitacao_contrato, name='nova_solicitacao_contrato'),

    path('elaboracao_contrato/', views.elaboracao_contrato, name='elaboracao_contrato'),
    path('elaboracao_contrato/<int:solicitacao_id>/cadastrar/', views.cadastrar_contrato, name='cadastrar_contrato'),
    path('elaboracao_minuta_contrato/<int:solicitacao_id>/cadastrar/', views.cadastrar_minuta_contrato, name='cadastrar_minuta_contrato'),
    path('detalhes_contrato/<int:pk>/', views.detalhes_contrato, name='detalhes_contrato'),
    path('detalhes_minuta_contrato/<int:pk>/', views.detalhes_minuta_contrato, name='detalhes_minuta_contrato'),

    path("solicitacoes/<int:pk>/inserir-minuta-bm/", views.inserir_minuta_bm, name="inserir_minuta_bm"),
    path("solicitacoes/<int:pk>/inserir-minuta-bm-contrato/", views.inserir_minuta_bm_contrato, name="inserir_minuta_bm_contrato"),

    path("bm/<int:pk>/detalhe/", views.detalhe_bm, name="detalhe_bm"),
    path("bm_contrato/<int:pk>/detalhe/", views.detalhe_bm_contrato, name="detalhe_bm_contrato"),
    path("bm/<int:pk>/aprovar/<str:papel>/", views.aprovar_bm, name="aprovar_bm"),
    path("bm/<int:pk>/reprovar/<str:papel>/", views.reprovar_bm, name="reprovar_bm"),
    path('bms/<int:bm_id>/avaliar/', views.avaliar_bm, name='avaliar_bm'),
    path("bm/<int:bm_id>/editar/", views.editar_bm, name="editar_bm"),
     path("evento/<int:evento_id>/cadastrar-nf/", views.cadastrar_nf, name="cadastrar_nf"),
    path("evento/<int:nf_id>/editar-nf/", views.editar_nf, name="editar_nf"),
    path("nf/<int:nf_id>/deletar/", views.deletar_nf, name="deletar_nf"),
    path('evento/<int:evento_id>/avaliar/', views.avaliar_evento_fornecedor, name='avaliar_evento_fornecedor'),

    path('contrato/<int:pk>/cadastrar-nf/', views.cadastrar_nf_cliente, name='cadastrar_nf_cliente'),
    path("contrato/<int:pk>/editar-nf/", views.editar_nf_cliente, name="editar_nf_cliente"),
    path("contrato/<int:pk>/excluir-nf/", views.excluir_nf_cliente, name="excluir_nf_cliente"),

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

    path('nova/', views.solicitar_os, name='solicitar_os'),
    path('ordem-servico/<int:pk>/', views.detalhe_os, name='detalhe_ordem_servico'),
    path('ordem-servico/<int:pk>/editar/', views.editar_ordem_servico, name='editar_ordem_servico'),
    path('ordem-servico/<int:pk>/lider/<str:acao>/', views.aprovar_os_lider, name='aprovar_os_lider'),
    path('ordem-servico/<int:pk>/upload-contrato/', views.upload_contrato_os, name='upload_contrato_os'),
    path('ordem-servico/<int:pk>/gerente-contrato/<str:acao>/', views.aprovar_os_gerente_contrato, name='aprovar_os_gerente_contrato'),
    path('ordens-servico/', views.lista_ordens_servico, name='lista_ordens_servico'),
    path("ordem-servicos/<int:pk>/", views.detalhes_os, name="detalhes_os"),
    path('ordem-servicos/novo/', OSCreateView.as_view(), name='nova_os'),
    path("ordem-servico/<int:pk>/registrar-entrega/", views.registrar_entrega_os, name="registrar_entrega_os"),


]
