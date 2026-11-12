"""Exportações gerenciais explícitas, sem dados bancários ou execução de fórmulas."""
from datetime import date,datetime
from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from . import financial_operations as fo,financial_queries as fq
from . import payment_queries as pq

MONEY_FORMAT='[$R$-pt-BR] #,##0.00;[Red]-[$R$-pt-BR] #,##0.00'


def safe_text(value):
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
    return value


def table(book,name,headers,records,*,money=(),dates=(),wrap=(),row_height=None):
    sheet=book.create_sheet(name)
    sheet.freeze_panes='A2'
    if row_height:sheet.sheet_format.defaultRowHeight=row_height
    for index in range(1,len(headers)+1):sheet.column_dimensions[get_column_letter(index)].width=24
    cells=[]
    for text in headers:
        cell=WriteOnlyCell(sheet,text);cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='0D7E66');cells.append(cell)
    sheet.append(cells)
    count=0
    for values in records:
        cells=[]
        for index,value in enumerate(values,1):
            cell=WriteOnlyCell(sheet,safe_text(value))
            if index in wrap:cell.alignment=Alignment(wrap_text=True,vertical='top')
            if index in money and isinstance(value,(int,float,Decimal)):cell.number_format=MONEY_FORMAT
            if index in dates and isinstance(value,(date,datetime)):cell.number_format='dd/mm/yyyy'
            cells.append(cell)
        sheet.append(cells);count+=1
    sheet.auto_filter.ref=f'A1:{get_column_letter(len(headers))}{count+1}'


def export_report(user,kind,form):
    filters=form.cleaned_data
    # Limites antes de gerar o arquivo, evitando exportações incompletas silenciosas.
    if kind=='contas':
        queryset=fo.accounts_query(user,filters)
        if queryset.count()>10000:raise fo.ProjectionLimit('Refine os filtros para exportar até 10.000 NFs.')
        rows=fo.account_rows(fq.eager_nfs(queryset).order_by('pk'),user)
        records=[]
        for row in rows:
            nf=row['record']
            records.append([nf.pk,row['supplier'].nome,nf.numero_nf,nf.serie,nf.tipo_documento,nf.contrato.num_contrato,
                row['project'].cod_projeto if row['project'] else '',row['origin_label'],row['number'],nf.valor_pago,nf.data_emissao,
                nf.data_pagamento,'Data informada no lançamento (legado)',row['operation_state'],
                'Válida' if row['authorized'] else 'Pendente / conferir','Sim' if nf.financeiro_autorizou else 'Não',
                row['payment_actor'] if nf.total_pago else '',bool(row['receipt_url']),
                nf.total_pago,nf.saldo_pendente,nf.situacao_liquidacao,nf.vencimento_original,row['due'],row['next_installment'],row['scheduled'],row['unscheduled'],row['renegotiated'],bool(nf.cancelada_em)])
    elif kind=='pagamentos':
        moves=fo.payments_query(user,filters)
        if moves.count()>10000:raise fo.ProjectionLimit('Refine os filtros para exportar até 10.000 movimentos.')
        moves=list(moves.select_related('nf__contrato__empresa_terceira','nf__contrato__cod_projeto','nf__os__cod_projeto','nf__bm','registrado_por').order_by('pk'))
        invoices={r['id']:r for r in fo.account_rows(fq.eager_nfs(fo.accounts_query(user,{**filters,'historico':True})).filter(pk__in={p.nf_id for p in moves}),user)}
        records=[]
        for p in moves:
            r=invoices[p.nf_id];nf=p.nf
            records.append([nf.pk,r['supplier'].nome,nf.numero_nf,nf.serie,nf.tipo_documento,nf.contrato.num_contrato,
                r['project'].cod_projeto if r['project'] else '',r['origin_label'],r['number'],p.valor,nf.data_emissao,
                p.data_pagamento,'Data efetiva declarada do movimento',r['operation_state'],'Válida' if r['authorized'] else 'Pendente / conferir',p.get_tipo_display(),
                str(p.registrado_por) if p.registrado_por else 'Responsável não identificado no histórico disponível.',bool(p.comprovante),
                p.pk,p.referencia_estorno_id,p.origem_registro,p.registrado_em.replace(tzinfo=None),pq.money(-p.centavos if p.tipo=='estorno' else p.centavos),p.programacao_id,nf.valor_pago])
    elif kind=='contratos':
        queryset=fo.budget_contracts(filters)
        if queryset.count()>1000:raise fo.ProjectionLimit('Refine os filtros para exportar até 1.000 contratos.')
        rows=fo.budget_rows(user,filters,queryset)
        records=[[r['contract'].num_contrato,r['contract'].empresa_terceira.nome,r['contract'].guarda_chuva,r['reference'],
            *[r['stats'][key] for key in ('previsto','medido','autorizado','faturado','pago','unpaid','measured_billed','planned_measured')],
            ' '.join(r['alerts'])] for r in rows]
    else:
        projection=fo.monthly_projection(user,filters)
    book=Workbook(write_only=True)
    if kind=='contas':
        table(book,'Contas a pagar',
            ['NF ID','Fornecedor','Número NF','Série','Tipo','Contrato','Projeto','Origem','BM','Valor NF','Emissão',
             'Data NF','Critério da data','Situação operacional','Autorização atual','Integralmente paga','Último responsável identificável','Comprovante cadastrado',
             'Total pago líquido','Saldo ativo','Liquidação','Vencimento original','Vencimento atual acordado','Próxima parcela','Saldo com programação','Saldo sem programação','Reprogramada','Cancelada'],records,money=(10,19,20,25,26),dates=(11,12,22,23,24))
    elif kind=='pagamentos':
        table(book,'Pagamentos',['NF ID','Fornecedor','Número NF','Série','Tipo','Contrato','Projeto','Origem','BM','Valor movimento','Emissão NF','Data efetiva declarada','Critério da data','Conferência atual da NF','Autorização atual','Tipo movimento','Responsável pelo registro','Comprovante cadastrado','Movimento ID','Referência estorno','Origem do registro','Instante de registro (UTC)','Efeito líquido','Parcela vinculada','Valor fiscal NF'],records,money=(10,23,25),dates=(11,12,22))
    elif kind=='contratos':
        table(book,'Posição contratual',['Contrato','Fornecedor','Guarda-chuva','Contratado vigente','Planejado','Medido','Autorizado','Faturado','Pago líquido por movimentos no período','Saldo ativo atual no escopo','Medido menos faturado','Planejado menos medido','Alertas'],records,money=range(4,13))
    else:
        metrics=('planned','paid','scheduled','rescheduled','authorized_unpaid','other_unpaid','review_balance','overdue')
        labels=['Planejado Evento/OS','Pago líquido por movimentos','Parcelas programadas','Parcelas reprogramadas','Saldo sem parcelas autorizado','Saldo sem parcelas não liberado','Saldo em conferência sem previsão confiável','Vencido (subconjunto das obrigações futuras)']
        table(book,'Mensal',['Mês',*labels],
            ([r['month'] or 'Sem data confiável',*[r[key] for key in metrics]] for r in projection['rows']),money=range(2,10),dates=(1,))
        table(book,'Fornecedor e projeto',['Mês','Fornecedor','Projeto',*labels],
            ([r['month'] or 'Sem data confiável',r['supplier'],r['project'],*[r[key] for key in metrics]] for r in projection['details']),money=range(4,12),dates=(1,))
    criteria=[['Relatório',kind],['Estado','Situação atual dos registros; não reconstrói autorização histórica.'],
        ['Datas','Caixa: data efetiva de cada movimento. NF: data informada no lançamento. Prazo: vencimento original ou acordo, nunca inferido do legado.'],
        ['Mensal','Parcelas futuras usam programação vigente; saldo sem parcelas usa vencimento confiável. Sem data/conciliação permanece explícito, inclusive em filtro de período.'],
        ['Saldos','Saldo ativo atual do escopo é independente da janela de caixa. Vencido é subconjunto das obrigações futuras, não um valor adicional.'],
        ['Valores','Etapas não se somam. BM é medição por participação; não é caixa. Sem saldo contratual definitivo.'],
        ['Aditivos','Referência integral do contrato; acréscimo sobre valor anterior, conforme metodologia existente.']]
    for key,value in filters.items():
        if value not in (None,'',False):criteria.append([str(form.fields[key].label),str(value)])
    table(book,'Critérios',['Critério','Valor'],criteria)
    output=BytesIO();book.save(output)
    return output.getvalue()
