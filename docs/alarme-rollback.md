# Alarme: como desfazer

O hub só **escuta**; ele não altera a central sozinho. A única coisa que muda na central é a
programação de IP/porta destino que você faz à mão. Desfazer = restaurar esses valores.

## Antes de mexer na central

Preencha o `alarme-valores.txt` (fica fora do Git) com os valores atuais. Sem eles não há volta exata.
Tire também fotos das telas de comunicação do Active Net/Mobile antes de editar.

## Se o alarme parar de funcionar

1. **Confirme que é a central e não o hub.** Abra o Active Mobile no celular. Se ele arma/desarma, a
   central está bem e o problema é só a aba do hub; vá ao passo 4.
2. **Restaure a programação da central** com os valores do `alarme-valores.txt`:
   IP destino (endereços 702/703) e porta destino (706/707), ou no Active Net/Mobile
   (comunicação → IP destino 1 e porta destino 1). Use a senha de instalador.
3. Teste de novo pelo Active Mobile. Se ainda falhar, é a rede ou o módulo ME-04, não o hub.
4. **Desligue o hub sem desfazer a central:** apague ou renomeie o `alarm.json` e reinicie a bandeja.
   A aba Alarme passa a mostrar "não configurado" e a porta deixa de ser aberta.
5. **Volte o código** ao estado sem alarme, se precisar:
   `git checkout de008e9 -- .` (último commit sem alarme) ou `git revert 7ac75fe`.

## Causas comuns de "parou de conectar"

| Sintoma | Causa provável | Correção |
|---|---|---|
| Aba diz "Aguardando a central conectar…" | IP do PC mudou (DHCP) e a central aponta para o antigo | Reserve o IP do PC no roteador e reprograme a central |
| Idem, após reiniciar o Windows | Firewall bloqueou a porta | Libere a porta para a rede privada |
| Idem | IP da central mudou e o `panel_ip` do `alarm.json` não bate | Reserve o IP da central e atualize o `alarm.json` |
| "Não foi possível escutar na porta" | Outro programa usa a porta | Mude `port` no `alarm.json` e na central |
| Active Mobile parou, hub funciona | Programação da central foi alterada | Restaure os valores originais (passo 2) |

## Estado do projeto quando o alarme foi adicionado (2026-10-27)

- Commit sem alarme: `de008e9` (renomeação para casa-hub). Commit com alarme: `7ac75fe`.
- Repositório renomeado de `ac-control` para `casa-hub` (o link antigo redireciona).
- PC: Ethernet `192.168.1.15`, gateway `192.168.1.1`, **DHCP ligado** (o IP pode mudar).
- Nenhuma alteração foi feita na central pelo hub até esta data.
