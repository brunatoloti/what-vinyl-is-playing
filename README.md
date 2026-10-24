# Lado A

Aplicação Streamlit para reconhecer o som do vinil pelo microfone do aparelho que acessa a página. Inclui capa em destaque, captura automática por WebRTC, gravação manual e histórico em tabela com miniaturas.

## Executar

Use Python 3.11 ou 3.12.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Antes, configure o Google Sheets conforme abaixo. Para rodar localmente, copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e preencha os campos. Não publique credenciais no GitHub.

## Google Sheets com o conector

1. Crie uma planilha exclusiva para o histórico e uma aba com o nome exato `Historico`.
2. Importe `historico_modelo.csv` nessa aba ou cole na primeira linha estes cabeçalhos, nas colunas A a H:

   `id, identificada_em, musica, artista, album, capa_url, link, chave`

3. No Google Cloud, ative Google Sheets API e Google Drive API.
4. Crie uma conta de serviço e gere a chave JSON. Copie os campos desse JSON para a seção `[connections.gsheets]` dos Secrets.
5. Compartilhe a planilha como **Editor** com o endereço `client_email` da conta de serviço.
6. Preencha `spreadsheet` com a URL da planilha.

A aplicação usa `st.connection("gsheets", type=GSheetsConnection)`, `conn.read()` e `conn.update()`. Ela não usa SQLite, arquivos locais de histórico ou outro banco. O histórico persistente fica integralmente na planilha. A coluna `capa_url` guarda o endereço da imagem, exibida sob demanda. A imagem não é incorporada à célula nem copiada para outro armazenamento.

Dedique essa aba à aplicação: `update()` regrava a tabela completa. Não adicione fórmulas, outras colunas ou conteúdo adicional nela. O bloqueio no servidor protege as atualizações dentro de um único processo. Use uma única instância da aplicação; duas instalações ou edições simultâneas na planilha podem causar perda de atualizações. Esse modelo atende uso pessoal e históricos pequenos; o tempo de gravação cresce com a tabela.

## Reconhecimento

Esta versão usa [ShazamIO](https://github.com/shazamio/ShazamIO), uma biblioteca gratuita de integração **não oficial** com o Shazam. Não exige token do Shazam, assinatura de reconhecimento ou conta pessoal no Spotify. Não há promessa de acesso ilimitado, disponibilidade ou continuidade: mudanças e limites do Shazam podem interromper o reconhecimento.

O trecho é processado pelo ShazamIO, que gera uma assinatura acústica e consulta o Shazam. O app não funciona totalmente offline. A resposta pode fornecer título, artista, álbum, capa e link.

Instale FFmpeg no computador antes de iniciar (por exemplo, `sudo apt install ffmpeg` no Ubuntu ou `brew install ffmpeg` no macOS). No Windows, instale FFmpeg e adicione sua pasta bin ao PATH. No Streamlit Community Cloud, o arquivo `packages.txt` inclui essa dependência.

### Automático

- Clique em START e autorize o microfone. O navegador sempre exige consentimento inicial.
- Deixe o aparelho próximo às caixas e a página aberta, com a tela ativa.
- O app mantém até 15 segundos de áudio em memória e processa os últimos 10 segundos para consultar o reconhecimento a cada intervalo configurado. O padrão é 60 segundos, com teto teórico de 60 consultas por hora.
- A identificação não acontece exatamente na troca da faixa: há atraso de captura, intervalo e resposta da API. Músicas muito curtas podem ser ignoradas.
- Trechos praticamente silenciosos não são enviados. O limiar é básico e pode precisar de ajuste conforme o microfone.
- STOP encerra a captura. A última identificação continua visível e recebe esse rótulo; ela não comprova que a música ainda está tocando.
- Navegar para Histórico remove o componente do microfone e interrompe a captura. Volte e clique em START para retomar.
- A captura pode parar se o celular bloquear a tela, o navegador for para segundo plano ou a conexão cair. Não é monitoramento em segundo plano.

### Por botão

Escolha Por botão, grave de 10 a 15 segundos usando o gravador nativo e clique em Identificar música. Essa alternativa não depende da conexão WebRTC. Use uma gravação nova a cada consulta.

### Como evitar duplicatas

A chave combina artista e título, normalizados para minúsculas. Consultas consecutivas da mesma faixa não criam novas entradas durante a sessão. Se outra música for identificada e a primeira voltar depois, ela poderá ser registrada novamente. Uma nova sessão também consulta a última linha para evitar duplicação da mesma faixa em menos de 10 minutos.

Limitação: se você repetir a mesma faixa imediatamente, sem outra faixa identificada no intervalo, ela será tratada como continuidade. Versões com o mesmo artista e título também podem ser agrupadas. O horário representa a identificação, não o instante exato em que a agulha chegou à faixa. O fuso é America/Sao_Paulo, com deslocamento gravado na planilha.

## Hospedar no Streamlit Community Cloud

1. Suba os arquivos para um repositório, incluindo `.streamlit/config.toml` e excluindo `secrets.toml`.
2. Crie o app com `app.py` como entrada e Python 3.11 ou 3.12.
3. Copie o conteúdo preenchido de `secrets.toml.example` para os Secrets do app.
4. Abra o app por HTTPS e autorize o microfone.

WebRTC pode precisar de um servidor TURN, conforme a rede e a hospedagem. Há um exemplo comentado em Secrets. STUN sozinho não garante conexão em todas as redes. Se START não estabelecer a captura, configure TURN ou use Por botão. Para acesso pelo celular ao app em outro computador, use HTTPS; HTTP de um IP da rede local normalmente não libera o microfone.

O app tem login privado para uma única conta, configurada nos Secrets. Reconhecimento, microfone e histórico só são criados após a autenticação. Sem configuração válida, o acesso fica bloqueado.

## Falhas de gravação e privacidade

Se o Sheets falhar, o registro fica pendente na memória da sessão e o app tenta novamente. Mantenha a sessão aberta para evitar perda dos registros ainda não confirmados. IDs únicos reduzem duplicação quando uma tentativa de gravação recebe resposta incerta. Não há fila persistente fora do Sheets.

O áudio não é salvo na planilha ou em disco pela aplicação. Ele transita pelo servidor Streamlit. O ShazamIO processa o trecho e consulta o serviço remoto, sujeito às políticas desse fornecedor. Credenciais ficam nos Secrets da hospedagem. Preferências temporárias e buffers existem apenas na memória da sessão; o histórico é a única informação persistida pelo app.

O catálogo pode retornar uma reedição, coletânea ou edição digital diferente do LP físico. A identificação não determina prensagem, país, número de catálogo ou lado do disco.

## Verificação

```bash
python -m unittest discover -s tests -v
```

Os testes verificam normalização dos metadados, fallback de capa, geração de WAV e deduplicação. O uso real de microfone, TURN, ShazamIO e Google Sheets precisa ser validado com suas credenciais e seu navegador.

Documentação consultada:

- https://github.com/streamlit/gsheets-connection
- https://github.com/whitphx/streamlit-webrtc
- https://github.com/shazamio/ShazamIO


## Configurar seu login privado

1. Após instalar as dependências, execute `python gerar_senha.py` no seu computador.
2. Crie uma senha com pelo menos 12 caracteres. O terminal não exibe nem salva sua senha.
3. Copie o hash gerado para os Secrets, junto das credenciais existentes do Sheets:

```toml
[access]
username = "seu_usuario"
password_hash = "COLE_O_HASH_GERADO_AQUI"
```

O hash usa PBKDF2-SHA256, sal aleatório e 600 mil iterações. Não coloque a senha original na planilha, no código ou no GitHub. As credenciais são configuração privada da hospedagem; os dados de músicas continuam apenas no Google Sheets.

Abra o app e entre com o usuário escolhido e a senha original. Não existe cadastro público. O botão Sair encerra o acesso e limpa os dados da sessão, inclusive o buffer do microfone. Registros ainda pendentes podem ser perdidos ao sair; o app avisa quando houver pendências.

O login vale para a sessão atual do navegador, sem cookie de login persistente. Recarregar a página ou perder a sessão pode exigir nova entrada. Alterar usuário ou hash nos Secrets invalida sessões anteriores na próxima execução. Cinco erros causam pausa de 30 segundos naquela sessão; isso não é um bloqueio global contra ataques distribuídos. Para uma camada adicional, restrinja também o acesso ao app nas opções da hospedagem, quando disponível.

As capas são buscadas de URLs públicas do catálogo, mas o histórico e as consultas da aplicação ficam protegidos pelo login. Use HTTPS na hospedagem.
