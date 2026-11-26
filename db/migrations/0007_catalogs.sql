-- WE · 0007 · Catálogos globais aprovados (sem dados de clientes).

INSERT INTO legacy.source_systems (source_system_code, name, technology, role_in_phase1, notes_pt) VALUES
 ('CRMCONTAB',      'CrmContab',        'Firebird',            'origem_migracao',
  '218 tabelas, 217 PK, praticamente sem FK declaradas; relações inferidas só após reconciliação de órfãos. Credenciais em texto simples na origem: nunca migrar.'),
 ('FILOSOFT_SNC32', 'Filosoft / SNC32', 'NAO_INDICADO',        'system_of_record_contabilistico',
  'Mantém-se como sistema de registo contabilístico na Fase 1. A WE recebe apenas read models (saldos, balancetes, estados, SAF-T validado).'),
 ('SIGEP32',        'SIGEP32',          'DBISAM',              'origem_migracao',
  'Parte do DDL da pasta transversal do pacote corresponde ao modelo SIGEP32 e não ao kernel WE. Utilitários de desencriptação DBISAM não são executados sem autorização explícita.'),
 ('SAFT',           'SAF-T (PT)',       'XML',                 'read_model_contabilistico',
  'Estrutura e versão do schema a validar em fonte oficial AT antes de uso produtivo (VALIDACAO_EXTERNA_PENDENTE).'),
 ('CENTRALGEST',    'CentralGest',      'NAO_INDICADO',        'origem_a_avaliar', 'Tecnologia e âmbito não indicados no repositório.'),
 ('GIMO32',         'Gimo32',           'NAO_INDICADO',        'origem_a_avaliar', 'Tecnologia e âmbito não indicados no repositório.')
ON CONFLICT (source_system_code) DO NOTHING;

INSERT INTO platform.capabilities (capability_code, layer, description_pt, side_effects) VALUES
 ('event_store.append',      'Foundation',            'Registar evento material no Event Store', 'internal'),
 ('evidence.store',          'Document and Evidence', 'Guardar evidência imutável com SHA-256', 'internal'),
 ('decision.propose',        'Governance',            'Propor decisão (humano ou IA)', 'internal'),
 ('decision.approve',        'Governance',            'Aprovar ou rejeitar decisão (apenas humano)', 'internal'),
 ('ai.summarize',            'Intelligence',          'Resumir conteúdo autorizado (sem efeitos laterais)', 'none'),
 ('ai.classify',             'Intelligence',          'Classificar conteúdo autorizado (sem efeitos laterais)', 'none'),
 ('ai.propose_decision',     'Intelligence',          'Redigir proposta de decisão para validação humana', 'none'),
 ('signal.promote',          'Opportunity',           'Promover sinal a oportunidade', 'internal'),
 ('knowledge.import',        'Knowledge',             'Importar depósito de conhecimento validado por JSON Schema', 'internal'),
 ('communication.send',      'Communication Runtime', 'Enviar comunicação externa (DESATIVADO nesta fase)', 'external'),
 ('obligation.submit',       'Obligation and Compliance', 'Submissão a AT/SS (DESATIVADO nesta fase)', 'external')
ON CONFLICT (capability_code) DO NOTHING;
UPDATE platform.capabilities SET enabled = false WHERE side_effects = 'external';

INSERT INTO obligation.rule_catalog (rule_id, rule_code, version, jurisdiction, title_pt, effective_from, rule_spec, source_ref)
VALUES ('00000000-0000-4000-8000-00000000a001', 'EXEMPLO_SINTETICO_MENSAL', 1, 'PT',
        'Regra sintética de exemplo (não normativa)', '2026-01-01',
        '{"periodicity":"monthly","due":{"day_of_month":20,"month_offset":1}}',
        'SINTETICO — não corresponde a qualquer norma real')
ON CONFLICT DO NOTHING;
