# THOUGHTS

Documento para alinhar as features antes de mexer no código.

## Contexto do projeto

- O bot atual é um fork de um chatbot de Discord focado em conversar com LLMs.
- A base hoje já suporta múltiplos provedores OpenAI-compatible, troca de modelo e contexto por reply chain.
- Para o seu uso, o objetivo deixa de ser um bot "genérico e sarcástico" e passa a ser um bot de apoio acadêmico e técnico para um servidor privado.

## Objetivo do novo bot

Criar um bot confiável para:

1. Pesquisa acadêmica em Direito e Programação com padrão ABNT.
2. Geração de snippets de código com explicação linha por linha e referências úteis para iniciantes.
3. Montagem de planos de estudo realistas até a data da prova.
4. Apoio de revisão com quiz, simulado e monitoria do progresso.

## Princípios de produto

- Priorizar utilidade e precisão acima de estilo.
- Responder com fontes quando a tarefa exigir pesquisa externa.
- Separar claramente o que é fato, interpretação e sugestão.
- Manter o bot adequado para um servidor privado, com controle de acesso e sem comportamento agressivo por padrão.
- Permitir entrega da resposta no canal ou por DM quando isso for mais útil para o usuário.

## Features desejadas

### 1. Modo de pesquisa acadêmica

O bot deve:

- Fazer web-search antes de responder.
- Priorizar fontes confiáveis e atualizadas.
- Gerar texto em formato de relatório, com estrutura compatível com ABNT.
- Produzir referências bibliográficas e links das fontes usadas.
- Diferenciar Direito de Programação, porque os critérios de fonte mudam bastante entre as áreas.

Perguntas para decidir depois:

- O relatório deve sair em tom formal, com sumário, introdução, desenvolvimento e conclusão?
- O bot deve citar apenas fontes públicas, ou também aceitar PDFs e páginas paginadas?
- Deve haver limite de tamanho para evitar relatórios enormes demais?

### 2. Modo de geração de código

O bot deve:

- Gerar snippets em qualquer linguagem.
- Explicar cada linha ou bloco com comentários no próprio código.
- Incluir links para artigos, documentação oficial e material para iniciantes.
- Indicar pré-requisitos quando o trecho usar conceitos mais avançados.

Perguntas para decidir depois:

- Os comentários devem ser realmente linha a linha sempre, ou apenas quando o usuário pedir?
- O bot deve preferir documentação oficial em vez de tutoriais?
- Deve haver um formato padrão de saída para código, explicação e links?

### 3. Modo de plano de estudo

O bot deve:

- Receber assuntos, data da prova e disponibilidade semanal.
- Montar um cronograma realista com blocos de estudo.
- Distribuir revisão, prática e simulado.
- Ajustar o plano ao tempo disponível e ao volume do conteúdo.

Perguntas para decidir depois:

- O bot deve pedir dias e horários livres em formato livre ou guiado?
- O plano deve ser diário, semanal, ou híbrido?
- Deve recalcular o plano quando o usuário informar progresso ou atraso?

### 4. ABNT helper

O bot deve:

- Formatar referências e citações conforme ABNT.
- Conferir se um texto básico está com a estrutura acadêmica esperada.
- Ajudar a transformar links, livros, artigos e PDFs em referências prontas.
- Sugerir ajustes de padronização sem reescrever o conteúdo inteiro.

### 5. Modo Monitor

O bot deve:

- Acompanhar o progresso de estudo por usuário ou por grupo.
- Registrar tópicos concluídos, pendentes e com dificuldade.
- Identificar quais assuntos mais aparecem no servidor e quais precisam de reforço.
- Resumir a evolução da turma em relatórios curtos.

### 6. Quiz / Simulado

O bot deve:

- Gerar perguntas de múltipla escolha, dissertativas e verdadeiro/falso.
- Montar simulados por tema, nível de dificuldade e quantidade de questões.
- Corrigir respostas com explicação e indicar onde o aluno errou.
- Permitir banco de questões reaproveitável a partir dos materiais do servidor.

### 7. Entrega por DM

O bot deve:

- Poder enviar a resposta no canal, em DM, ou em um modo híbrido.
- Usar DM quando a resposta for longa, privada ou quando o usuário preferir.
- Opcionalmente postar um aviso curto no servidor dizendo que o conteúdo completo foi enviado por DM.

Perguntas para decidir depois:

- O padrão deve ser canal-first, DM-first, ou depender do tipo de tarefa?
- O usuário poderá escolher o destino da resposta por comando?
- O bot deve manter um resumo curto no servidor quando a resposta for enviada por DM?

## Direção técnica sugerida

- Antes de pensar em fine-tuning, validar se prompts fortes + perfis de comportamento resolvem o uso real.
- Criar modos de operação separados, em vez de um único prompt genérico.
- Adicionar suporte explícito a web-search e coleta de fontes.
- Criar ferramentas de apoio para ABNT, monitoramento e simulados.
- Adicionar um modo de entrega configurável entre canal, DM e híbrido.
- Estruturar saídas com templates previsíveis para facilitar leitura no Discord.
- Manter permissões por usuário/canal para um servidor privado.

## Itens que provavelmente vão precisar mudar no código

- Prompt do sistema.
- Comandos slash para escolher o tipo de tarefa.
- Integração com busca na web.
- Formatação de resposta para relatórios, código e cronogramas.
- Fluxos específicos para ABNT, monitoria e quizzes.
- Fluxos de entrega por DM e fallback de resposta privada.
- Configuração de fontes, limites e comportamento por modo.

## Ordem sugerida de implementação

1. Definir o escopo de cada modo.
2. Criar prompts e formatos de saída por tarefa.
3. Implementar busca na web e citações.
4. Implementar o modo de código com comentários e links.
5. Implementar o modo de estudo com coleta de disponibilidade.
6. Implementar ABNT helper, monitoria e simulados.
7. Implementar entrega configurável por DM.
8. Só depois avaliar fine-tuning, se ainda houver ganho claro.

