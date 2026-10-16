# Assinatura de código

Este documento explica por que o Windows (e o macOS) desconfiam de programas sem assinatura
digital, quais caminhos existem para assinar o PeliculaConverter, quanto custam e como ligar
cada um no CI. **Hoje os pacotes saem sem assinatura**; o workflow já está pronto para assinar
assim que houver um certificado.

> Preços e regras mudam com frequência. Os valores abaixo são **aproximados** (outubro de 2026)
> e servem só para comparar: confira sempre a página oficial de cada serviço antes de decidir.

## Por que o Windows avisa

- **SmartScreen.** Quando um arquivo baixado da internet é aberto, o Windows consulta a
  reputação dele na Microsoft. Arquivo sem assinatura aparece como *Editor desconhecido* e, se
  for novo (poucos downloads), o SmartScreen mostra *O Windows protegeu o computador*. O usuário
  ainda consegue abrir em **Mais informações → Executar assim mesmo**, mas muita gente desiste.
- **Antivírus.** Os antivírus usam heurísticas. Executáveis gerados pelo PyInstaller costumam
  receber **falsos positivos**, porque o mesmo carregador também é usado por programas
  maliciosos. A assinatura ajuda (o arquivo passa a ter um autor identificável), mas não elimina
  o problema: se um antivírus acusar, envie o arquivo como falso positivo ao fabricante (no caso
  do Microsoft Defender, pelo portal de envio de arquivos da Microsoft).
- **Assinar não dá reputação instantânea.** Mesmo assinado, um programa novo pode continuar
  recebendo o aviso até acumular downloads sem problemas. A diferença é que a reputação passa a
  ficar ligada ao **certificado/editor** e se acumula entre versões; sem assinatura, cada versão
  nova é um arquivo desconhecido e começa do zero. Certificados **EV** já deram reputação
  imediata, mas a Microsoft encerrou esse tratamento especial em 2024: hoje OV e EV precisam
  construir reputação do mesmo jeito.

## Regras que valem para qualquer certificado público

- Desde **junho de 2023** (requisitos do CA/Browser Forum), a chave privada de **todo**
  certificado de assinatura de código emitido por uma autoridade pública precisa ficar em
  hardware certificado: token USB, cartão inteligente ou HSM na nuvem. Na prática **não dá mais
  para comprar um certificado e receber um arquivo `.pfx`** para colocar num segredo do GitHub.
  Para assinar no CI é preciso um serviço de assinatura na nuvem (SignPath, Azure, ou o serviço
  em nuvem da própria autoridade, geralmente mais caro).
- Desde **março de 2026** a validade máxima de um certificado de assinatura de código caiu para
  **460 dias** (cerca de 15 meses): conte com renovação todo ano.
- **Carimbo de tempo** (*timestamp*): a assinatura feita com carimbo continua válida depois que o
  certificado vence. O `assinar.ps1` usa `http://timestamp.digicert.com`.

## As opções

| Opção | Custo aproximado | Para quem | Assina no CI? |
|---|---|---|---|
| [SignPath Foundation](https://signpath.org/) | **Grátis** para projetos de código aberto | Repositório **público**, licença aprovada pela OSI, sem componentes proprietários, build automatizado; precisa de aprovação | Sim (action do SignPath) |
| [Certum Open Source Code Signing](https://shop.certum.eu/) | ~€ 30–70 por ano (mais o leitor/cartão, se for a versão em cartão) | Desenvolvedor pessoa física com projeto de código aberto | Difícil: a chave fica no cartão ou no SimplySign (nuvem com app e login) |
| [Azure Artifact Signing](https://azure.microsoft.com/pricing/details/artifact-signing/) (antigo *Trusted Signing*) | ~US$ 10 por mês (plano Basic) | Empresas nos EUA, Canadá, União Europeia e Reino Unido e pessoas físicas nos EUA e Canadá (regra de elegibilidade de 2026; **confira**, porque muda) | Sim (action da Microsoft) |
| Certificado OV ou EV de autoridade comercial (DigiCert, Sectigo, GlobalSign, SSL.com…) | Algumas centenas de US$ por ano (EV costuma custar mais) | Qualquer pessoa ou empresa que passe pela validação | Só com o serviço de nuvem da autoridade (custo extra) ou assinando localmente com o token |
| [Apple Developer Program](https://developer.apple.com/programs/) (macOS) | US$ 99 por ano | Para assinar com *Developer ID* e **notarizar** o `.app`/`.dmg` | Sim (`codesign` + `notarytool` no runner macOS) |
| Linux | Grátis | Não existe assinatura de executável equivalente | — |

Observações:

- **SignPath Foundation**: o certificado é emitido em nome da *SignPath Foundation*, que passa a
  aparecer como editor do programa; o projeto precisa publicar uma política de assinatura de
  código (normalmente uma seção no README) e seguir as regras deles. É a opção mais barata e a
  que melhor combina com o PeliculaConverter (MIT, build 100% no GitHub Actions). A aprovação não
  é automática.
- **Certum Open Source**: o certificado sai em nome do desenvolvedor ("Open Source Developer,
  Nome"). Funciona bem para assinar **no próprio computador** com o cartão ou o SimplySign
  (veja "Assinar localmente" abaixo); automatizar no CI é complicado.
- **Azure Artifact Signing**: os certificados são de curta duração e renovados pela Microsoft;
  a identidade é validada antes. Para quem mora no Brasil, como pessoa física, hoje **não é
  elegível** (confira a regra atual).
- **macOS**: sem assinatura e notarização, o Gatekeeper bloqueia o app baixado; nas versões
  recentes do macOS o usuário precisa liberar em *Ajustes do Sistema → Privacidade e Segurança*.
  O suporte ao macOS está desativado no PeliculaConverter por enquanto.
- **Linux**: a integridade é conferida por **somas SHA-256**: toda release traz o
  `SHA256SUMS.txt`. Opcionalmente dá para assinar esse arquivo com uma chave GPG
  (`SHA256SUMS.txt.asc`) ou publicar atestados de origem do GitHub
  (`actions/attest-build-provenance` + `gh attestation verify`). Repositórios `apt` assinam o
  índice com GPG, não cada `.deb`.

## Como ligar no CI

O workflow [`.github/workflows/build.yml`](../.github/workflows/build.yml) assina, nesta ordem:
`PeliculaConverter.exe` e `pelicula-cli.exe` (antes de montar o `.msi` e o `.zip`, para que os
dois levem os executáveis assinados) e depois o próprio `.msi`. Sem segredos, esses passos são
pulados e o build segue normalmente.

### Opção A: certificado `.pfx` (já ligada; basta cadastrar os segredos)

Serve para um certificado com chave exportável (por exemplo, um certificado antigo, emitido antes
de junho de 2023, ou um certificado de teste). Cadastre dois segredos do repositório:

```powershell
# No PowerShell, na pasta do certificado:
[Convert]::ToBase64String([IO.File]::ReadAllBytes("certificado.pfx")) | Set-Content -NoNewline cert.b64
gh secret set WINDOWS_CERT_PFX_BASE64 -R edvitor13/pelicula-converter < cert.b64
gh secret set WINDOWS_CERT_PASSWORD -R edvitor13/pelicula-converter   # o gh pede a senha
Remove-Item cert.b64
```

O passo *Conferir se há certificado de assinatura* passa a dizer "Certificado encontrado" e o
[`packaging/windows/assinar.ps1`](../packaging/windows/assinar.ps1) assina com `signtool`
(SHA-256 + carimbo de tempo da DigiCert), conferindo cada assinatura com `signtool verify /pa`.

Para **testar o caminho** sem gastar nada, use um certificado autoassinado. A assinatura fica
válida, mas não é confiável para outros computadores (não ajuda com o SmartScreen):

```powershell
$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=PeliculaConverter (teste)" `
       -CertStoreLocation Cert:\CurrentUser\My
$senha = Read-Host -AsSecureString "Senha do .pfx"
Export-PfxCertificate -Cert $c -FilePath teste.pfx -Password $senha
```

### Opção B: SignPath Foundation

1. Peça a inclusão do projeto em <https://signpath.org/> (o repositório precisa ser público).
2. No SignPath, configure o projeto, a *artifact configuration* (os `.exe` e o `.msi`), a
   política de assinatura e o GitHub como *trusted build system*.
3. Cadastre o segredo `SIGNPATH_API_TOKEN` e as variáveis `SIGNPATH_ORGANIZATION_ID`,
   `SIGNPATH_PROJECT_SLUG` e `SIGNPATH_POLICY_SLUG`:

   ```bash
   gh secret set SIGNPATH_API_TOKEN -R edvitor13/pelicula-converter
   gh variable set SIGNPATH_ORGANIZATION_ID -R edvitor13/pelicula-converter --body "<id>"
   gh variable set SIGNPATH_PROJECT_SLUG -R edvitor13/pelicula-converter --body "pelicula-converter"
   gh variable set SIGNPATH_POLICY_SLUG -R edvitor13/pelicula-converter --body "release-signing"
   ```

4. No `build.yml`, descomente o bloco **SignPath** (logo depois de *Assinar os executáveis*) e
   repita o envio + assinatura para o `.msi` depois de *Montar o instalador .msi*.
5. Publique a política de assinatura de código no README, como o programa exige.

### Opção C: Azure Artifact Signing

1. Numa assinatura do Azure, crie uma conta do *Artifact Signing*, faça a validação de
   identidade e crie um *certificate profile* do tipo *Public Trust*.
2. Crie um registro de aplicativo (Entra ID) com a função de assinante do perfil de certificado
   (*Artifact Signing Certificate Profile Signer*) e um segredo de cliente.
3. Cadastre os segredos `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` e `AZURE_CLIENT_SECRET` e as
   variáveis `AZURE_SIGNING_ENDPOINT` (por exemplo `https://eus.codesigning.azure.net/`),
   `AZURE_SIGNING_ACCOUNT` e `AZURE_CERT_PROFILE`.
4. No `build.yml`, descomente o bloco **Azure Artifact Signing** e repita o passo para o `.msi`
   (`files-folder: ${{ github.workspace }}` e `files-folder-filter: msi`). Confira os nomes das
   entradas no README da action `azure/artifact-signing-action`, que já mudaram uma vez.

### Assinar localmente (cartão, token ou SimplySign)

Com o certificado no repositório de certificados do Windows (cartão/token conectado ou SimplySign
aberto), defina a impressão digital (SHA-1) do certificado e rode o build local:

```bat
set WINDOWS_CERT_SHA1=0123456789ABCDEF0123456789ABCDEF01234567
build.bat
```

O `build.bat` chama o `assinar.ps1`, que usa `signtool sign /sha1 ...` para os executáveis e
para o `.msi`. Para uma release assinada desse jeito, publique os arquivos gerados localmente
(e gere o `SHA256SUMS.txt` com eles).

## Conferir uma assinatura e as somas

```powershell
Get-AuthenticodeSignature .\PeliculaConverter.exe | Format-List   # Windows
signtool verify /pa /v .\PeliculaConverter-v1.1.0-windows-x64.msi
Get-FileHash .\PeliculaConverter-v1.1.0-windows-x64.msi -Algorithm SHA256
```

```bash
sha256sum -c SHA256SUMS.txt --ignore-missing   # Linux, na pasta dos arquivos baixados
```
