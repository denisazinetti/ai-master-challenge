import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell} from 'recharts';
import './styles.css';

const fmt = new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 1});
const pct = v => `${(v * 100).toFixed(1)}%`;
// Mirrors diagnostics.REVIEW_THRESHOLD; chosen from the held-out coverage × accuracy curve (Classificador tab).
const REVIEW_THRESHOLD = 0.5;
const COLORS = {Alto:'#ef4444', Médio:'#f59e0b', Baixo:'#10b981'};
const CONF_COLORS = ['#79e4c2', '#f59e0b', '#94a5bf'];
const NLP_CATEGORIES = [
  'Hardware',
  'Software',
  'Access',
  'Administrative rights',
  'HR Support',
  'Internal Project',
  'Purchase',
  'Storage'
];

const ROUTING_QUEUES = [
  'Fila N1 · Hardware & Periféricos',
  'Fila N1 · Acessos & Credenciais',
  'Fila N2 · Software & Aplicações',
  'Fila N2 · Projetos Internos',
  'Fila Administrativa & RH',
  'Fila Financeiro & Compras',
  'Mesa Estratégica CS · Retenção'
];

const QUEUE_TABS = [
  { id: '', label: 'Todas as Filas', icon: '◈' },
  { id: 'triage', label: 'Mesa de Triagem', icon: '📥', desc: 'Chamados com baixa confiança (<50%) retidos para validação manual de categoria' },
  { id: 'copilot', label: 'Filas N1/N2 · Copiloto', icon: '⚡', desc: 'Roteamento 100% automático por alta confiança — rascunhos prontos para envio' },
  { id: 'cs_retention', label: 'Mesa CS & Retenção', icon: '🚨', desc: 'Chamados críticos e contas com risco de cancelamento (proteção direta de ARR)' },
  { id: 'finance', label: 'Financeiro & Billing', icon: '💰', desc: 'Dúvidas de fatura, cobrança e estorno (compliance manual estrito)' }
];

function Risk({risk}) { return <span className={`risk risk-${risk.level.toLowerCase()}`}>{risk.level} · {risk.score}</span> }

function getTicketQueue(ticket) {
  if (ticket.routedQueue) return ticket.routedQueue;
  if (ticket.auto_queue) return ticket.auto_queue;
  const isBilling = ticket.ticket_type === 'Billing inquiry';
  const isCritical = ticket.priority === 'Critical';
  const isHighRisk = ticket.risk?.level === 'Alto';
  const needsReview = ticket.classification?.needs_review;

  if (needsReview) return 'Mesa de Triagem (Revisão NLP)';
  if (isHighRisk || isCritical) return 'Mesa Estratégica CS & Retenção';
  if (isBilling) return 'Fila Financeiro & Billing';
  const cat = ticket.classification?.category || 'Hardware';
  return cat === 'Hardware' || cat === 'Access' || cat === 'Storage' ? `Fila N1 · ${cat}` : `Fila N2 · ${cat}`;
}

function getAutomationStatus(ticket) {
  if (ticket.triageConfirmed) {
    return {
      label: `Triado (${ticket.routedQueue?.split('·')[0]?.trim() || 'Roteado'})`,
      badgeClass: 'status-confirmed',
      hint: `Triagem confirmada pelo analista · Fila: ${ticket.routedQueue}`,
      icon: '✓'
    };
  }
  const isBilling = ticket.ticket_type === 'Billing inquiry';
  const isCritical = ticket.priority === 'Critical';
  const isHighRisk = ticket.risk?.level === 'Alto';
  const needsReview = ticket.classification?.needs_review;

  if (isBilling || isCritical || isHighRisk) {
    const reason = isBilling ? 'Financeiro / Compliance' : isCritical ? 'Prioridade Crítica' : 'Risco de Churn';
    return {
      label: 'Humano obrigatório',
      badgeClass: 'status-human',
      hint: `${reason} — bloqueado para automação direta`,
      icon: '🛡️'
    };
  }
  if (needsReview) {
    return {
      label: 'Revisão de triagem',
      badgeClass: 'status-review',
      hint: 'Confiança NLP < 50% — validar categoria antes de rotear',
      icon: '⚠'
    };
  }
  return {
    label: 'Copiloto liberado',
    badgeClass: 'status-copilot',
    hint: 'Alta confiança & elegível — roteado automaticamente',
    icon: '⚡'
  };
}

function App() {
  const [tab, setTab] = useState('executivo');
  const [data, setData] = useState(null);
  const [tickets, setTickets] = useState([]);
  const [selected, setSelected] = useState(null);
  const [filters, setFilters] = useState({priority:'', risk:'', queue:'', search:''});
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [modelMetrics, setModelMetrics] = useState(null);
  const [classifierText, setClassifierText] = useState('');
  const [classifierAutoRun, setClassifierAutoRun] = useState(false);

  useEffect(() => { fetch('/api/overview').then(r => r.json()).then(setData) }, []);
  useEffect(() => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    fetch(`/api/tickets?${q}`).then(r => r.json()).then(setTickets);
  }, [filters]);
  useEffect(() => { fetch('/api/model-metrics').then(r => r.ok ? r.json() : null).then(setModelMetrics).catch(() => {}) }, []);

  const riskData = useMemo(() => data ? Object.entries(data.overview.risk_counts || {}).map(([name, value]) => ({name, value})) : [], [data]);

  const testInClassifier = useCallback((ticket) => {
    const fullText = ticket.description && ticket.description.trim()
      ? `${ticket.subject}\n\n${ticket.description}`
      : ticket.subject;
    setClassifierText(fullText);
    setClassifierAutoRun(true);
    setTab('classificador');
  }, []);

  const onConfirmTriage = useCallback((ticketId, updatedData) => {
    setTickets(prev => prev.map(t => t.id === ticketId ? {...t, ...updatedData} : t));
    setSelected(prev => prev && prev.id === ticketId ? {...prev, ...updatedData} : prev);
  }, []);

  async function openTicket(id) {
    setDraft(null);
    const t = await fetch(`/api/tickets/${id}`).then(r => r.json());
    setDraft(t.copilot_draft || null);
    setSelected(t);
    setTab('ticket');

    const isAutoCopilot = !t.classification?.needs_review &&
      t.ticket_type !== 'Billing inquiry' &&
      t.priority !== 'Critical' &&
      t.risk?.level !== 'Alto';

    if (isAutoCopilot && !t.copilot_draft) {
      setLoading(true);
      fetch('/api/copilot/draft', {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({ticket_id: t.id})
      })
      .then(r => r.json())
      .then(setDraft)
      .catch(() => {})
      .finally(() => setLoading(false));
    }
  }

  async function generate() {
    if (!selected) return;
    setLoading(true);
    try {
      setDraft(await fetch('/api/copilot/draft', {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({ticket_id: selected.id})
      }).then(r => r.json()));
    } finally {
      setLoading(false);
    }
  }

  if (!data) return <main className="loading">Carregando inteligência operacional…</main>;
  if (!data.ready) return <main className="loading">{data.message}</main>;

  const TAB_TITLES = {
    executivo: 'Onde o suporte perde tempo — e onde recuperar retenção',
    triagem: 'Fila priorizada por urgência de negócio',
    diagnostico: 'O que os dados provam — e o que não provam',
    churn: 'Evidência complementar de retenção',
    classificador: 'Playground do classificador NLP',
    ticket: 'Copiloto do agente',
  };

  return <div className="shell">
    <aside>
      <div className="brand"><span>◈</span><div>G4Desk<small>Suporte &amp; Retenção</small></div></div>
      <nav>
        {[['executivo','Visão executiva'],['triagem','Central de triagem'],['diagnostico','Diagnóstico estatístico'],['classificador','Classificador NLP'],['churn','Validação de retenção']].map(([id,label]) =>
          <button className={tab===id ? 'active' : ''} onClick={() => setTab(id)} key={id}>{label}</button>
        )}
      </nav>
      <footer>Challenge 002<br/><strong>Operações + IA responsável</strong></footer>
    </aside>
    <main>
      <header>
        <div>
          <p className="eyebrow">CENTRO DE INTELIGÊNCIA OPERACIONAL</p>
          <h1>{TAB_TITLES[tab] || TAB_TITLES.ticket}</h1>
        </div>
        <div className="status">● Dados reais carregados</div>
      </header>
      {tab === 'executivo' && <Executive data={data} riskData={riskData} modelMetrics={modelMetrics}/>}
      {tab === 'triagem' && <Triage tickets={tickets} filters={filters} setFilters={setFilters} openTicket={openTicket} testInClassifier={testInClassifier} insights={data.triage_insights}/>}
      {tab === 'diagnostico' && <Diagnostics data={data}/>}
      {tab === 'classificador' && <Classifier modelMetrics={modelMetrics} text={classifierText} setText={setClassifierText} autoRun={classifierAutoRun} setAutoRun={setClassifierAutoRun}/>}
      {tab === 'churn' && <Churn data={data}/>}
      {tab === 'ticket' && selected && <Ticket ticket={selected} draft={draft} generate={generate} loading={loading} back={() => setTab('triagem')} testInClassifier={testInClassifier} onConfirmTriage={onConfirmTriage}/>}
    </main>
  </div>;
}

/* ─── Visão Executiva ─── */
function Executive({data, riskData, modelMetrics}) {
  const o = data.overview;
  return <>
    <section className="metrics">
      {[
        ['Tickets analisados', fmt.format(o.tickets)],
        ['1ª resposta média', o.avg_first_response_hours === null ? 'N/D' : `${o.avg_first_response_hours}h`],
        ['Resolução média', `${o.avg_resolution_hours}h`],
        ['CSAT médio', `${o.avg_csat}/5`],
        ['Risco alto', fmt.format(o.high_risk)],
      ].map(([a, b]) => <article key={a}><span>{a}</span><strong>{b}</strong></article>)}
    </section>

    {o.data_quality_note && <p className="warning">Qualidade de dados: {o.data_quality_note}</p>}

    <section className="grid two">
      <article className="panel">
        <h2>Risco operacional</h2>
        <p>Índice explicável de retenção, não uma probabilidade de churn.</p>
        <div className="chart">
          <ResponsiveContainer><PieChart><Pie data={riskData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={80}>{riskData.map(x => <Cell key={x.name} fill={COLORS[x.name]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer>
        </div>
      </article>
      <article className="panel">
        <h2>ROI por cenário</h2>
        <div className="scenario scenario-head"><span/><span>Volume do dataset ({fmt.format(data.roi.volumes.dataset_tickets)}/ano)</span><span>Volume do briefing ({fmt.format(data.roi.volumes.brief_tickets_per_year)}/ano)</span></div>
        {data.roi.scenarios.map(x => <div className="scenario scenario-three" key={x.name}><b>{x.name}</b><span><strong>US$ {fmt.format(x.annual_capacity_value_usd)}</strong><small>{x.monthly_hours_released}h/mês</small></span><span><strong>US$ {fmt.format(x.annual_capacity_value_usd_brief)}</strong><small>{x.monthly_hours_released_brief}h/mês</small></span></div>)}
        <small>Capacidade potencial de agentes (US$ {data.roi.assumptions.cost_per_hour_usd}/h), só rascunho assistido; não representa corte de equipe. Sem custo de implementação: ver business case.</small>
      </article>
    </section>

    {/* ─── Métricas do Modelo NLP ─── */}
    {modelMetrics && <section className="panel model-metrics-section">
      <h2>Classificador NLP — Validação no Dataset 2</h2>
      <p className="model-algo">{modelMetrics.algorithm}</p>
      <div className="model-headline">
        <article className="model-stat">
          <span>Acurácia</span>
          <strong>{pct(modelMetrics.accuracy)}</strong>
        </article>
        <article className="model-stat">
          <span>Macro-F1</span>
          <strong>{pct(modelMetrics.macro_f1)}</strong>
        </article>
        <article className="model-stat">
          <span>Treino</span>
          <strong>{fmt.format(modelMetrics.train_rows)}</strong>
        </article>
        <article className="model-stat">
          <span>Teste</span>
          <strong>{fmt.format(modelMetrics.test_rows)}</strong>
        </article>
      </div>
      <div className="model-categories">
        <div className="cat-head"><span>Categoria</span><span>Precision</span><span>Recall</span><span>F1</span></div>
        {modelMetrics.labels.map(label => {
          const m = modelMetrics.by_category[label];
          return <div className="cat-row" key={label}>
            <span>{label}</span>
            <span>{pct(m.precision)}</span>
            <span>{pct(m.recall)}</span>
            <span className={m.f1 >= 0.85 ? 'metric-good' : m.f1 >= 0.70 ? 'metric-ok' : 'metric-warn'}>{pct(m.f1)}</span>
          </div>;
        })}
      </div>
      <small>{modelMetrics.note}</small>
    </section>}

    <section>
      <h2>Três decisões para segunda-feira</h2>
      <div className="insights">
        {data.insights.map(x => <article className="insight" key={x.title}><h3>{x.title}</h3><p>{x.detail}</p><strong>{x.action}</strong></article>)}
      </div>
    </section>
  </>;
}

/* ─── Central de Triagem ─── */
function Triage({tickets, filters, setFilters, openTicket, testInClassifier, insights}) {
  const activeQueueInfo = QUEUE_TABS.find(q => q.id === (filters.queue || ''));

  return <>
    {insights && <section className="triage-intelligence" aria-label="Indicadores gerenciais da triagem">
      <div className="triage-intelligence-head">
        <div><p className="eyebrow">VISÃO GERENCIAL</p><h2>Onde agir primeiro</h2></div>
        <small>{insights.scope}</small>
      </div>
      <div className="triage-kpis">
        <article><span>Backlog aberto</span><strong>{fmt.format(insights.open_tickets)}</strong></article>
        <article><span>Risco alto</span><strong className="metric-warn">{fmt.format(insights.high_risk)}</strong></article>
        <article><span>Críticos</span><strong className="metric-warn">{fmt.format(insights.critical)}</strong></article>
        <article><span>Temas recorrentes</span><strong>{fmt.format(insights.recurring_themes)}</strong><small>3+ tickets abertos</small></article>
      </div>
      <div className="triage-insight-grid">
        <article className="panel triage-risk-chart"><h3>Backlog por risco</h3><div className="triage-risk-content"><ResponsiveContainer width="100%" height={270}><PieChart><Pie data={insights.risk_distribution} dataKey="value" nameKey="name" innerRadius={70} outerRadius={110}>{insights.risk_distribution.map(x => <Cell key={x.name} fill={COLORS[x.name]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer><div className="risk-legend">{insights.risk_distribution.map(item => <div key={item.name}><span style={{backgroundColor: COLORS[item.name]}}/><b>{item.name}</b><strong>{fmt.format(item.value)}</strong></div>)}</div></div></article>
        <article className="panel bottleneck-panel"><h3>Ranking de gargalos</h3><div className="bottleneck-list">{insights.bottlenecks.map((item, index) => <div className="bottleneck-row" key={`${item.ticket_type}-${item.subject}`}><span className="bottleneck-rank">#{index + 1}</span><div><b>{item.subject}</b><small>{item.ticket_type} · {item.open_tickets} não encerrados</small><em>{item.action}</em></div>{(item.high_risk > 0 || item.critical > 0) && <span className="bottleneck-alert">{item.critical ? `${item.critical} crítico${item.critical > 1 ? 's' : ''}` : `${item.high_risk} risco alto`}</span>}</div>)}</div></article>
      </div>
      <p className="triage-data-note"><b>Fonte:</b> {insights.source_note} {insights.limitation}</p>
    </section>}

    <div className="filters">
      <input placeholder="Buscar assunto, cliente ou categoria NLP" value={filters.search} onChange={e => setFilters({...filters, search: e.target.value})}/>
      <select value={filters.priority} onChange={e => setFilters({...filters, priority: e.target.value})}>
        <option value="">Toda prioridade</option>
        {['Critical','High','Medium','Low'].map(x => <option key={x}>{x}</option>)}
      </select>
      <select value={filters.risk} onChange={e => setFilters({...filters, risk: e.target.value})}>
        <option value="">Todo risco</option>
        {['Alto','Médio','Baixo'].map(x => <option key={x}>{x}</option>)}
      </select>
    </div>
    <div className="queue-nav queue-nav-table" aria-label="Filtro por fila de atendimento">
      {QUEUE_TABS.map(q => (
        <button
          key={q.id}
          type="button"
          className={`queue-tab ${filters.queue === q.id ? 'active' : ''}`}
          onClick={() => setFilters({...filters, queue: q.id})}
        >
          <span className="queue-icon">{q.icon}</span>
          <span className="queue-label">{q.label}</span>
        </button>
      ))}
    </div>
    {activeQueueInfo?.desc && <div className="queue-desc-banner queue-desc-table"><span className="queue-desc-icon">{activeQueueInfo.icon}</span><span><b>{activeQueueInfo.label}:</b> {activeQueueInfo.desc}</span></div>}
    <div className="panel table">
      <div className="table-head">
        <span>Ticket</span>
        <span>Canal</span>
        <span>Prioridade</span>
        <span>Risco</span>
        <span>Classificação NLP</span>
        <span>Fila de Atendimento</span>
        <span style={{textAlign:'right'}}>Auditar</span>
      </div>
      {tickets.slice(0,150).map(t =>
        <button className="ticket-row" onClick={() => openTicket(t.id)} key={t.id}>
          <span><b>#{t.id} · {t.subject}</b><small>{t.customer_name} · {t.ticket_type}{t.resolution_hours != null ? ` · ${t.resolution_hours}h` : ''}</small></span>
          <span>{t.channel}</span>
          <span>{t.priority}</span>
          <span><Risk risk={t.risk}/></span>
          <span>
            <div className="nlp-badge-group">
              <span className="nlp-category">{t.classification?.category || 'N/D'}</span>
              <span className={`nlp-conf ${t.classification?.confidence >= REVIEW_THRESHOLD ? 'metric-good' : t.classification?.confidence >= 0.40 ? 'metric-ok' : 'metric-warn'}`}>
                {t.classification ? `${(t.classification.confidence * 100).toFixed(0)}%` : ''}
              </span>
              {t.classification?.needs_review && (
                <span className="nlp-review-tag" title="Confiança abaixo de 50% — exige confirmação humana">
                  ⚠ Revisão
                </span>
              )}
            </div>
          </span>
          <span>
            {(() => {
              const qName = getTicketQueue(t);
              const isAutoCopilot = !t.classification?.needs_review && t.ticket_type !== 'Billing inquiry' && t.priority !== 'Critical' && t.risk?.level !== 'Alto';
              return (
                <div className="queue-cell">
                  <span className="queue-cell-name">{qName}</span>
                  {isAutoCopilot ? (
                    <span className="auto-route-pill" title="Roteado automaticamente por alta confiança">⚡ Auto</span>
                  ) : t.triageConfirmed ? (
                    <span className="human-route-pill" title="Triagem confirmada pelo analista">✓ Manual</span>
                  ) : t.classification?.needs_review ? (
                    <span className="pending-route-pill" title="Aguardando validação de triagem">⚠ Pendente</span>
                  ) : (
                    <span className="specialized-route-pill" title="Fila especializada / CS">🛡️ Humano</span>
                  )}
                </div>
              );
            })()}
          </span>
          <span className="row-action">
            <span
              role="button"
              tabIndex={0}
              className="btn-nlp"
              title="Auditar as Top 3 alternativas e probabilidades no classificador"
              onClick={e => { e.stopPropagation(); testInClassifier(t); }}
              onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); testInClassifier(t); } }}
            >
              🔍 Auditar
            </span>
          </span>
        </button>
      )}
    </div>
    <small>Mostrando até 150 registros da fila filtrada. A esteira IA aplica guardrails: billing, chamados críticos e risco alto exigem ação humana direta.</small>
  </>;
}

/* ─── Playground do Classificador NLP ─── */
function Classifier({modelMetrics, text, setText, autoRun, setAutoRun}) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const classify = useCallback(async (overrideText) => {
    const val = overrideText !== undefined ? overrideText : text;
    if (!val || val.trim().length < 5) return;
    setLoading(true); setError(null); setResult(null);
    try {
      const res = await fetch('/api/classify', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({text: val})});
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Erro ao classificar'); }
      setResult(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [text]);

  useEffect(() => {
    if (autoRun && text && text.trim().length >= 5) {
      classify(text);
      if (setAutoRun) setAutoRun(false);
    }
  }, [autoRun, text, classify, setAutoRun]);

  const handleKeyDown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) classify(); };

  return <>
    <section className="panel classifier-panel">
      <h2>Teste o classificador em tempo real</h2>
      <p>Cole ou digite o texto de um ticket de suporte (ou envie direto da triagem) e veja a classificação em 8 categorias do Dataset 2.</p>
      <textarea
        className="classifier-input"
        placeholder="Ex: My laptop screen is flickering after the latest update. I've tried restarting but the issue persists. The display goes black intermittently..."
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={5}
      />
      <div className="classifier-actions">
        <button className="primary" disabled={loading || !text || text.trim().length < 5} onClick={() => classify()}>
          {loading ? 'Classificando…' : 'Classificar ticket'}
        </button>
        {text && <button type="button" className="secondary" onClick={() => { setText(''); setResult(null); }}>Limpar</button>}
        <small className="classifier-hint">Ctrl+Enter para enviar · Mínimo 5 caracteres</small>
      </div>

      {error && <p className="warning">{error}</p>}

      {result && <div className="classifier-result">
        <div className="result-main">
          <div className="result-category">
            <span className="eyebrow">CATEGORIA PREDITA</span>
            <h3>{result.category}</h3>
            {result.needs_review ? (
              <span className="review-flag review-flag-warn">⚠ Confiança &lt; 50% · Requer triagem manual antes do roteamento</span>
            ) : (
              <span className="review-flag review-flag-ok">✓ Confiança ≥ 50% · Elegível para roteamento e rascunho assistivo</span>
            )}
          </div>
          <div className="result-confidence">
            <span className="conf-label">Confiança</span>
            <div className="conf-bar-bg">
              <div className="conf-bar-fill" style={{width: pct(result.confidence), background: result.confidence >= REVIEW_THRESHOLD ? '#79e4c2' : result.confidence >= 0.40 ? '#f59e0b' : '#ef4444'}}/>
            </div>
            <strong className={result.confidence >= REVIEW_THRESHOLD ? 'metric-good' : result.confidence >= 0.40 ? 'metric-ok' : 'metric-warn'}>
              {pct(result.confidence)}
            </strong>
          </div>
        </div>

        <div className="result-alternatives">
          <span className="eyebrow">TOP 3 CATEGORIAS</span>
          {result.alternatives.map((alt, i) => (
            <div className="alt-row" key={alt.category}>
              <span className="alt-rank">#{i+1}</span>
              <span className="alt-name">{alt.category}</span>
              <div className="alt-bar-bg">
                <div className="alt-bar-fill" style={{width: pct(alt.confidence), background: CONF_COLORS[i]}}/>
              </div>
              <span className="alt-pct">{pct(alt.confidence)}</span>
            </div>
          ))}
        </div>

        {result.similar_cases?.length > 0 && <div className="result-similar">
          <span className="eyebrow">CASOS SIMILARES NO HISTÓRICO (Dataset 2)</span>
          {result.similar_cases.map((c, i) => <div className="similar" key={i}><b>{c.category} · similaridade {c.score}</b><p>{c.text}</p></div>)}
        </div>}

        <div className="result-explain">
          <p><b>Limiar de revisão:</b> Quando a confiança fica abaixo de 50%, o sistema marca o ticket para revisão humana obrigatória — o agente deve confirmar a categoria antes do roteamento.</p>
        </div>
      </div>}
    </section>

    <ThresholdCurve metrics={modelMetrics}/>

    <section className="panel">
      <h2>Como funciona</h2>
      <div className="insights">
        <article className="insight">
          <h3>Vetorização</h3>
          <p>O texto é convertido em TF-IDF com n-grams (1–2), capturando termos isolados e expressões de duas palavras.</p>
          <strong>60.000 features máximas com sublinear TF</strong>
        </article>
        <article className="insight">
          <h3>Classificação</h3>
          <p>Regressão logística multinomial via SGD, treinada com balanceamento de classes no Dataset 2.</p>
          <strong>8 categorias · Split estratificado 80/20</strong>
        </article>
        <article className="insight">
          <h3>Guardrails</h3>
          <p>Abaixo de 50% de confiança, o ticket exige revisão manual. Billing, críticos e compensações nunca são automatizados.</p>
          <strong>IA assiste, humano decide</strong>
        </article>
      </div>
    </section>
  </>;
}

/* ─── Detalhe do Ticket ─── */
function Ticket({ticket, draft, generate, loading, back, testInClassifier, onConfirmTriage}) {
  const [copied, setCopied] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState(ticket.classification?.category || 'Hardware');
  const [selectedQueue, setSelectedQueue] = useState(
    ticket.routedQueue || ticket.auto_queue || getTicketQueue(ticket)
  );

  const isEligibleAuto = !ticket.classification?.needs_review &&
    ticket.ticket_type !== 'Billing inquiry' &&
    ticket.priority !== 'Critical' &&
    ticket.risk?.level !== 'Alto';

  const [routedSuccess, setRoutedSuccess] = useState(ticket.triageConfirmed || isEligibleAuto);
  const [showReclassify, setShowReclassify] = useState(false);

  const st = getAutomationStatus(ticket);
  const isChanged = selectedCategory !== ticket.classification?.category;

  const handleConfirm = () => {
    setRoutedSuccess(true);
    setShowReclassify(false);
    if (onConfirmTriage) {
      onConfirmTriage(ticket.id, {
        triageConfirmed: true,
        routedQueue: selectedQueue,
        classification: {
          ...ticket.classification,
          category: selectedCategory,
          needs_review: false,
          human_adjusted: isChanged
        }
      });
    }
  };

  return <>
    <button className="back" onClick={back}>← Voltar à fila</button>
    <section className="ticket-title">
      <div>
        <p className="eyebrow">TICKET #{ticket.id} · {ticket.ticket_type}</p>
        <h2>{ticket.subject}</h2>
        <p>{ticket.description}</p>
      </div>
      <Risk risk={ticket.risk}/>
    </section>
    <section className="grid two">
      <article className="panel triage-decision-panel">
        <div className="panel-header-action">
          <h2>Triagem &amp; Roteamento</h2>
          {routedSuccess && (
            <span className={`status-pill ${isEligibleAuto && !ticket.triageConfirmed ? 'status-copilot' : 'status-confirmed'}`}>
              {isEligibleAuto && !ticket.triageConfirmed ? '⚡ Roteado (IA)' : '✓ Roteado'}
            </span>
          )}
        </div>

        <div className="triage-status-row">
          <span><b>Classificação NLP:</b> {ticket.classification?.category} · {(ticket.classification?.confidence*100).toFixed(0)}%</span>
          {testInClassifier && <button type="button" className="btn-nlp-inline" onClick={() => testInClassifier(ticket)}>Auditar no NLP →</button>}
        </div>

        {routedSuccess && !showReclassify ? (
          <div className="triage-success-box">
            <div className="triage-success-icon">{isEligibleAuto && !ticket.triageConfirmed ? '⚡' : '✓'}</div>
            <div>
              <strong>{isEligibleAuto && !ticket.triageConfirmed ? 'Roteado Automaticamente pela IA' : 'Triagem Confirmada com Sucesso'}</strong>
              <p>Categoria: <b>{selectedCategory}</b> · Fila: <b>{selectedQueue}</b></p>
              <button type="button" className="btn-reclassify-link" onClick={() => setShowReclassify(true)}>
                ✎ Reclassificar categoria ou transferir de fila
              </button>
            </div>
          </div>
        ) : (
          <div className="triage-form">
            {ticket.classification?.needs_review && (
              <div className="triage-review-callout">
                ⚠ <b>Revisão de triagem obrigatória:</b> O modelo teve confiança abaixo de 50%. Valide a categoria e selecione a fila antes do atendimento.
              </div>
            )}
            <div className="form-group">
              <label>Categoria validada pelo analista:</label>
              <select className="triage-select" value={selectedCategory} onChange={e => setSelectedCategory(e.target.value)}>
                {NLP_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              {isChanged && <span className="category-changed-tag">🔄 Categoria alterada pelo agente (Active Learning)</span>}
            </div>

            <div className="form-group">
              <label>Fila de destino:</label>
              <select className="triage-select" value={selectedQueue} onChange={e => setSelectedQueue(e.target.value)}>
                {ROUTING_QUEUES.map(q => <option key={q} value={q}>{q}</option>)}
              </select>
            </div>

            <div className="form-actions-row">
              <button type="button" className="primary btn-route" onClick={handleConfirm}>
                ✓ Confirmar e Despachar
              </button>
              {showReclassify && (
                <button type="button" className="secondary" onClick={() => setShowReclassify(false)}>
                  Cancelar
                </button>
              )}
            </div>
          </div>
        )}

        <hr/>
        <h3>Sinais de Risco do Chamado</h3>
        {ticket.risk.factors.length
          ? ticket.risk.factors.map(f => <div className="factor" key={f.label}><span>{f.label}</span><b>{f.points > 0 ? '+' : ''}{f.points}</b></div>)
          : <p>Sem sinais fortes de risco operacional.</p>}
        <hr/>
        <p><b>Playbook sugerido:</b> {ticket.risk.level === 'Alto' ? 'Encaminhar para CS em até 1 dia útil com histórico e plano de recuperação.' : 'Resolver pela fila de suporte e monitorar nova recorrência.'}</p>
      </article>
      <article className="panel copilot-panel">
        <div className="panel-header-action">
          <h2>Copiloto do agente</h2>
          <span className={`status-pill ${st.badgeClass}`} title={st.hint}>
            <span className="status-pill-icon">{st.icon}</span> {st.label}
          </span>
        </div>
        <div className="governance-badge">
          <strong>🛡️ Human-in-the-loop:</strong> Este sistema gera rascunhos assistivos. O envio autônomo sem aprovação humana é bloqueado por política de conformidade e CSAT.
        </div>
        {ticket.response_playbook && (
          <div className="response-playbook">
            <strong>{ticket.response_playbook.title}</strong>
            <p>{ticket.response_playbook.instructions}</p>
          </div>
        )}
        {(ticket.ticket_type === 'Billing inquiry' || ticket.priority === 'Critical') && (
          <div className="policy-alert">
            🔒 <b>Chamado {ticket.ticket_type === 'Billing inquiry' ? 'Financeiro (Billing)' : 'Crítico'}:</b> Sugestões são estritamente orientativas; a resposta deve ser checada e assinada pelo analista.
          </div>
        )}
        {isEligibleAuto ? (
          <div className="copilot-auto-state" role="status" aria-live="polite">
            {loading
              ? '⚡ Gerando sugestão automaticamente…'
              : '⚡ Sugestão gerada automaticamente ao abrir o ticket.'}
          </div>
        ) : (
          <div className="copilot-action-bar">
            <button className="primary" disabled={loading} onClick={generate}>
              {loading ? 'Gerando…' : 'Gerar sugestão de resposta'}
            </button>
          </div>
        )}
        {draft && <div className="draft">
          <div className="draft-top">
            <small>{draft.mode === 'llm' ? 'LLM configurado' : 'Modo fallback'}</small>
            <button
              type="button"
              className="btn-copy"
              onClick={() => {
                if (navigator.clipboard) {
                  navigator.clipboard.writeText(draft.draft);
                }
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
            >
              {copied ? '✓ Copiado!' : '📋 Copiar resposta'}
            </button>
          </div>
          <p>{draft.draft}</p>
          <em>{draft.guardrail}</em>
        </div>}
      </article>
    </section>
    <section className="panel">
      <h2>Casos similares</h2>
      <p>Sem casos exibidos de propósito: no Dataset 1 a busca por similaridade de texto fica no nível do acaso (ver Diagnóstico estatístico). Use o playbook de resposta acima ou cole o texto no Classificador NLP, onde a busca é validada.</p>
    </section>
  </>;
}

/* ─── Diagnóstico estatístico ─── */
const pctInt = v => `${Math.round(v * 100)}%`;

function MiniBar({value, max = 1, color = '#79e4c2'}) {
  return <div className="mini-bar"><div style={{width: `${Math.min(100, (value / max) * 100)}%`, background: color}}/></div>;
}

function Diagnostics({data}) {
  const audit = data.data_audit, csat = data.csat_drivers, backlog = data.backlog, text = data.text_signal_check, retrieval = data.retrieval_eval, matrix = data.channel_priority_matrix;
  const channels = [...new Set(matrix.map(x => x.channel))], priorities = ['Critical', 'High', 'Medium', 'Low'];
  const cell = (channel, priority) => matrix.find(x => x.channel === channel && x.priority === priority);
  const maxBacklog = Math.max(...matrix.map(x => x.backlog_share)), minBacklog = Math.min(...matrix.map(x => x.backlog_share));
  const textBest = text.results[0];
  return <>
    <section className="metrics diag-kpis">
      {[
        ['Tickets não encerrados', pctInt(backlog.share), `${fmt.format(backlog.not_closed)} de ${fmt.format(audit.tickets)}`],
        ['Críticos sem encerramento', fmt.format(backlog.critical_not_closed), `p=${backlog.priority_chi2_p} · sem diferença significativa`],
        ['Drivers de CSAT detectados', `${csat.significant_variables.length} de ${csat.variables.length}`, 'Kruskal–Wallis, FDR 5%'],
        ['Pares de tempo impossíveis', pctInt(audit.resolution_before_first_response_share), 'resolução antes da 1ª resposta'],
        ['Texto prevê o tipo (D1)', pct(textBest.accuracy), `acaso = ${pct(textBest.chance)}`],
      ].map(([a, b, c]) => <article key={a}><span>{a}</span><strong>{b}</strong><small>{c}</small></article>)}
    </section>

    <section className="panel diag-verdict">
      <p className="eyebrow">LEITURA DO DIAGNÓSTICO</p>
      <h2>O que os dados sustentam — e o que eles não sustentam</h2>
      <ul>
        <li><b>O gargalo real é o backlog, não a velocidade.</b> {pctInt(backlog.share)} dos tickets não estão encerrados ({fmt.format(backlog.pending_customer)} aguardam o cliente) e a taxa em Critical e Low é estatisticamente indistinta (p={backlog.priority_chi2_p}): não há evidência de que a prioridade declarada esteja orientando o atendimento.</li>
        <li><b>Nenhuma variável observável explica a satisfação.</b> {csat.conclusion} Canal, prioridade, tipo, produto, perfil e tempo não separam clientes satisfeitos de insatisfeitos neste dataset — otimizar “o canal certo” seria ruído.</li>
        <li><b>O Dataset 1 não carrega sinal textual.</b> Um modelo treinado no próprio texto acerta o tipo do ticket no nível do acaso; a recuperação de casos similares também. A automação por texto é validada no Dataset 2 ({pct(data.model_metrics.accuracy)} de acurácia) e entra no Dataset 1 sempre com revisão humana.</li>
        <li><b>Decisão de produto:</b> o índice de risco é uma <i>regra de política</i> transparente, não um modelo ajustado. Pesos fixos, fatores visíveis e auditáveis por ticket.</li>
      </ul>
    </section>

    <section className="grid two">
      <article className="panel">
        <h2>Backlog por prioridade</h2>
        <p>Parcela de tickets não encerrados (Open + Pending customer).</p>
        {backlog.by_priority.sort((a, b) => ['Critical', 'High', 'Medium', 'Low'].indexOf(a.name) - ['Critical', 'High', 'Medium', 'Low'].indexOf(b.name)).map(x =>
          <div className="diag-row" key={x.name}><span>{x.name}</span><MiniBar value={x.share} color={x.name === 'Critical' ? '#ef4444' : '#79e4c2'}/><b>{pctInt(x.share)}</b><small>{fmt.format(x.not_closed)}/{fmt.format(x.tickets)}</small></div>)}
        <h2 style={{marginTop: 22}}>Backlog por tipo</h2>
        {backlog.by_type.map(x => <div className="diag-row" key={x.name}><span>{x.name}</span><MiniBar value={x.share}/><b>{pctInt(x.share)}</b><small>{fmt.format(x.not_closed)}/{fmt.format(x.tickets)}</small></div>)}
      </article>
      <article className="panel">
        <h2>Canal × prioridade — backlog</h2>
        <p>Mapa de calor da parcela não encerrada. Diferenças entre células ficam dentro do ruído amostral (n≈500 por célula).</p>
        <div className="heat" style={{gridTemplateColumns: `90px repeat(${priorities.length}, 1fr)`}}>
          <span/>{priorities.map(p => <b key={p}>{p}</b>)}
          {channels.map(ch => <React.Fragment key={ch}><b>{ch}</b>{priorities.map(pr => {
            const c = cell(ch, pr), t = (c.backlog_share - minBacklog) / Math.max(maxBacklog - minBacklog, 0.001);
            return <span key={pr} className="heat-cell" style={{background: `rgba(239,68,68,${0.15 + t * 0.45})`}} title={`${c.tickets} tickets`}>{pctInt(c.backlog_share)}</span>;
          })}</React.Fragment>)}
        </div>
      </article>
    </section>

    <section className="panel">
      <h2>O que influencia a satisfação (CSAT)?</h2>
      <p>{csat.method} Base: {fmt.format(csat.n)} tickets encerrados, CSAT médio {csat.mean_csat}/5. Spearman tempo × CSAT: ρ={csat.resolution_spearman.rho} (p={csat.resolution_spearman.p_value}, n={fmt.format(csat.resolution_spearman.n)}).</p>
      <div className="table compact diag-table">
        <div className="table-head"><span>Variável</span><span>n</span><span>p</span><span>p ajustado</span><span>Efeito ε²</span><span>Resultado</span></div>
        {csat.variables.map(v => <div className="ticket-row" key={v.variable}>
          <span><b>{v.variable}</b><small>{v.segments.length ? `${v.segments[0].segment} ${v.segments[0].csat} → ${v.segments[v.segments.length - 1].segment} ${v.segments[v.segments.length - 1].csat}` : ''}</small></span>
          <span>{fmt.format(v.n)}</span><span>{v.p_value}</span><span>{v.p_adjusted}</span><span>{v.effect_size}</span>
          <span className={v.significant ? 'metric-good' : 'metric-warn'}>{v.significant ? 'Significativo' : 'Sem efeito detectável'}</span>
        </div>)}
      </div>
      <p className="warning">Implicação: não existe alavanca comprovada sobre o CSAT nestes dados. A proposta mede resultado (CSAT, reabertura, backlog) em piloto controlado em vez de prometer ganho de satisfação.</p>
    </section>

    <Waste waste={data.waste}/>
    <Ranking ranking={data.combination_ranking}/>

    <section className="grid two">
      <article className="panel">
        <h2>Auditoria de qualidade dos dados</h2>
        {[
          ['Pares de timestamps', fmt.format(audit.timestamp_pairs)],
          ['Resolução antes da 1ª resposta', `${fmt.format(audit.resolution_before_first_response)} (${pctInt(audit.resolution_before_first_response_share)})`],
          ['Clientes com um único ticket', pctInt(audit.single_ticket_customers_share)],
          ['Descrições com placeholder não preenchido', fmt.format(audit.unfilled_template_placeholders)],
          ['Cobertura de CSAT (encerrados)', pctInt(audit.csat_coverage_closed)],
        ].map(([a, b]) => <div className="factor" key={a}><span>{a}</span><b className="neutral">{b}</b></div>)}
        <ul className="diag-list">{audit.findings.map(f => <li key={f}>{f}</li>)}</ul>
      </article>
      <article className="panel">
        <h2>Prova de sinal: onde o texto funciona</h2>
        <p>Cada experimento é avaliado em dados não vistos e comparado ao acaso.</p>
        {text.results.map(r => <div className="diag-row" key={r.target}><span>D1 · prever {r.target.toLowerCase()}</span><MiniBar value={r.accuracy}/><b>{pct(r.accuracy)}</b><small>acaso {pct(r.chance)}</small></div>)}
        <div className="diag-row"><span>D1 · casos similares (mesmo assunto)</span><MiniBar value={retrieval.dataset1.precision_at_k}/><b>{pct(retrieval.dataset1.precision_at_k)}</b><small>acaso {pct(retrieval.dataset1.chance)}</small></div>
        <div className="diag-row strong"><span>D2 · classificar 8 categorias</span><MiniBar value={data.model_metrics.accuracy}/><b>{pct(data.model_metrics.accuracy)}</b><small>acaso ≈ 19%</small></div>
        <div className="diag-row strong"><span>D2 · casos similares (mesma categoria)</span><MiniBar value={retrieval.dataset2.precision_at_k}/><b>{pct(retrieval.dataset2.precision_at_k)}</b><small>acaso {pct(retrieval.dataset2.chance)}</small></div>
        <p className="similar-intro">{retrieval.conclusion}</p>
      </article>
    </section>
  </>;
}

function Waste({waste}) {
  const a = waste.assumptions, w = waste.customer_wait;
  const usd = v => `US$ ${fmt.format(v)}`;
  return <section className="panel">
    <h2>Quanto estamos desperdiçando?</h2>
    <p>Horas de agente recuperáveis por ano, em dois volumes (arquivo e briefing). <b>São estimativas por premissa</b>: o dataset não mede esforço do agente. Custo-hora: US$ {a.cost_per_hour_usd}.</p>
    <div className="table compact diag-table waste-table">
      <div className="table-head"><span>Fonte de desperdício</span><span>Alavanca</span><span>h/ano (arquivo)</span><span>h/ano (briefing)</span><span>US$/ano (briefing)</span><span>Premissa</span></div>
      {waste.components.map(c => <div className="ticket-row" key={c.key}>
        <span><b>{c.name}</b></span><span>{c.lever}</span><span>{fmt.format(c.hours_year_dataset)}</span><span>{fmt.format(c.hours_year_brief)}</span><span>{usd(c.usd_year_brief)}</span><span><small>{c.assumption}</small></span>
      </div>)}
    </div>
    <div className="metrics waste-kpis">
      {[
        ['Recuperável por IA (briefing)', `${fmt.format(waste.ai_hours_year_brief)} h/ano`, `${usd(waste.ai_usd_year_brief)} · arquivo: ${fmt.format(waste.ai_hours_year_dataset)} h`],
        ['Maior desperdício', waste.largest_component, 'resolve-se com processo, não com IA'],
        ['Espera excedente do cliente', `${fmt.format(w.excess_hours_over_median)} h`, `${pctInt(w.excess_share_of_total)} do tempo observado em ${fmt.format(w.valid_pairs)} pares válidos`],
      ].map(([x, y, z]) => <article key={x}><span>{x}</span><strong className="waste-value">{y}</strong><small>{z}</small></article>)}
    </div>
    <p className="similar-intro"><b>Sensibilidade do backlog</b> (releituras por mês por ticket parado, volume do briefing): {waste.backlog_sensitivity.map(x => `${x.retouches_per_month}× → ${fmt.format(x.hours_year_brief)} h/ano`).join(' · ')}. {waste.caveat}</p>
  </section>;
}

function Ranking({ranking}) {
  return <section className="panel">
    <h2>Piores combinações canal × prioridade × tipo</h2>
    <p>{ranking.method} Base: {fmt.format(ranking.valid_pairs)} pares válidos em {ranking.combinations} combinações; média geral {ranking.overall_mean_hours}h.</p>
    <div className="table compact diag-table rank-table">
      <div className="table-head"><span>Combinação</span><span>n válido</span><span>Média (h)</span><span>± IC95</span><span>CSAT</span><span/></div>
      {ranking.worst.map((r, i) => <div className="ticket-row" key={`${r.channel}${r.priority}${r.type}`}>
        <span><b>#{i + 1} {r.channel} · {r.priority}</b><small>{r.type}</small></span><span>{r.n}</span><span>{r.mean_hours}</span><span>±{r.ci95}</span><span>{r.csat ?? '—'}</span><span/>
      </div>)}
    </div>
    <p className={ranking.is_signal ? 'similar-intro' : 'warning'}>{ranking.conclusion} Pior média observada: {ranking.worst_mean_hours}h; pior média esperada por acaso: {ranking.null_worst_mean_hours}h (p={ranking.permutation_p}).</p>
  </section>;
}

function ThresholdCurve({metrics}) {
  const curve = metrics?.threshold_curve;
  if (!curve) return null;
  const chosen = curve.find(r => r.threshold === REVIEW_THRESHOLD), strict = curve.find(r => r.threshold === 0.7);
  return <section className="panel">
    <h2>Por que o limiar de revisão é {pctInt(REVIEW_THRESHOLD)}</h2>
    <p>Em tickets nunca vistos: quanto do volume é roteado sem humano e com qual acurácia. Acima do limiar o ticket segue automático; abaixo, vai à Mesa de Triagem.</p>
    <div className="table compact diag-table">
      <div className="table-head"><span>Limiar</span><span>Roteado automático</span><span>Acurácia do automático</span><span>Vai para humano</span><span/><span/></div>
      {curve.filter(r => r.threshold > 0).map(r => <div className={`ticket-row ${r.threshold === REVIEW_THRESHOLD ? 'row-selected' : ''}`} key={r.threshold}>
        <span><b>≥ {pctInt(r.threshold)}</b>{r.threshold === REVIEW_THRESHOLD && <small>escolhido</small>}</span>
        <span>{pct(r.coverage)}</span><span>{r.accuracy === null ? '—' : pct(r.accuracy)}</span><span>{pct(r.sent_to_review)}</span><span/><span/>
      </div>)}
    </div>
    <p className="similar-intro">Sem limiar, a acurácia é {pct(curve[0].accuracy)}. Em {pctInt(REVIEW_THRESHOLD)} o automático atinge {pct(chosen.accuracy)} cobrindo {pct(chosen.coverage)} do volume; em 70% a acurácia sobe para {pct(strict.accuracy)}, mas só {pct(strict.coverage)} do volume ficaria automático.</p>
  </section>;
}

/* ─── Validação de Retenção ─── */
function Churn({data}) {
  const c = data.churn_validation;
  return <section className="panel">
    <h2>Validação complementar — Challenge 001</h2>
    <p>{c.method}</p>
    <div className="table compact">
      <div className="table-head"><span>Churn</span><span>Contas</span><span>Tickets/conta</span><span>Resolução (h)</span><span>CSAT</span><span>ARR</span></div>
      {c.comparison.map(x =>
        <div className="ticket-row" key={String(x.churn_flag)}>
          <span>{String(x.churn_flag) === 'true' ? 'Churnadas' : 'Retidas'}</span>
          <span>{x.accounts}</span><span>{x.tickets_per_account}</span><span>{x.resolution_hours}</span><span>{x.satisfaction}</span><span>US$ {fmt.format(x.arr)}</span>
        </div>
      )}
    </div>
    {c.tests && <>
      <h3 style={{marginTop: 22}}>Churnadas × retidas: há diferença no suporte?</h3>
      <div className="table compact diag-table">
        <div className="table-head"><span>Métrica</span><span>Churnadas</span><span>Retidas</span><span>p</span><span>p ajustado</span><span>Resultado</span></div>
        {c.tests.map(t => <div className="ticket-row" key={t.metric}><span><b>{t.metric}</b></span><span>{t.churned}</span><span>{t.retained}</span><span>{t.p_value}</span><span>{t.p_adjusted}</span><span className={t.significant ? 'metric-good' : 'metric-warn'}>{t.significant ? 'Significativo' : 'Sem diferença'}</span></div>)}
      </div>
      <p className="warning">{c.verdict}</p>
    </>}
    {c.churn_reasons && <>
      <h3 style={{marginTop: 22}}>Motivo declarado de churn</h3>
      <p>{c.churn_reasons.note}</p>
      {c.churn_reasons.by_reason.map(x => <div className="diag-row" key={x.reason}><span>{x.reason}</span><MiniBar value={x.share} max={0.25} color={x.reason === 'support' ? '#ef4444' : '#79e4c2'}/><b>{pctInt(x.share)}</b><small>{x.events} eventos</small></div>)}
      <p className="similar-intro">Suporte é citado em {pctInt(c.churn_reasons.by_reason.find(x => x.reason === 'support')?.share ?? 0)} dos eventos e em {c.churn_reasons.support_attributed_accounts} das {c.churn_reasons.churned_accounts} contas churnadas, que somam US$ {fmt.format(c.churn_reasons.support_attributed_arr)} de ARR ({pctInt(c.churn_reasons.support_arr_share)} do ARR perdido). É o teto de exposição. As contas que citam suporte não têm métricas de suporte piores do que as que citam outros motivos (todos p &gt; 0,1): o motivo declarado não coincide com o que os tickets mostram.</p>
    </>}
    <p className="warning">Limitação: {c.limitation}</p>
  </section>;
}

createRoot(document.getElementById('root')).render(<App/>);
