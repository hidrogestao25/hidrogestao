# App Gestao

Aplicação web em Django voltada para gestão de contratos, fornecedores, clientes, solicitações de prospecção e contratação, ordens de serviço, eventos, boletins de medição e acompanhamento financeiro.

## O que a aplicação faz

- Centraliza o fluxo de solicitações de prospecção, contratação e ordem de serviço.
- Controla contratos com clientes, contratos com fornecedores e contratos guarda-chuva.
- Organiza fornecedores, triagem, propostas, avaliações e indicadores.
- Acompanha eventos, entregas, boletins de medição, notas fiscais e previsões de pagamento.
- Separa permissões por grupo de usuário, como suprimento, liderança, gerência, diretoria e financeiro.

## Estrutura principal

- `HIDROGestao/`: configurações do projeto Django.
- `gestao_contratos/`: app principal com models, views, forms, templates e regras de negócio.
- `media/`: arquivos enviados pelos usuários.
- `static/`: arquivos estáticos da interface.

## Perfis de usuário

O sistema trabalha com grupos de acesso para definir responsabilidades e permissões, incluindo:

- Coordenador de Contrato
- Líder de Contrato
- Gerente
- Gerente e Líder de Contratos
- Gerente de Contratos
- Diretoria
- Financeiro
- Suprimento
- Fornecedor

## Desenvolvedor

O desenvolvedor identificado no histórico do repositório é:

- `hidromosaic <hidromosaic@gmail.com>`

## Observação

Caso a autoria precise refletir uma pessoa ou empresa com nome diferente do identificado no Git, basta atualizar esta seção do README.
