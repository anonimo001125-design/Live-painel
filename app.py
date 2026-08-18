def start_tunnel():
    global tunnel
    global tunnel_url

    line()
    log("[5] Iniciando túnel localhost.run...")

    # Encerra túnel anterior, se existir
    if tunnel is not None:

        try:

            if tunnel.poll() is None:
                tunnel.terminate()

                try:
                    tunnel.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    tunnel.kill()

        except Exception:
            pass

        tunnel = None

    command = [
        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        # Mantém a conexão viva
        "-o",
        "ServerAliveInterval=30",

        "-o",
        "ServerAliveCountMax=6",

        "-o",
        "TCPKeepAlive=yes",

        "-o",
        "ExitOnForwardFailure=yes",

        "-o",
        "ConnectTimeout=20",

        "-o",
        "ConnectionAttempts=3",

        # Túnel
        "-R",
        "80:127.0.0.1:8080",

        "nokey@localhost.run"
    ]

    try:

        tunnel = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

    except Exception as e:

        log(
            "[TUNEL] Erro ao iniciar SSH: "
            + str(e)
        )

        return None

    start = time.time()

    while time.time() - start < 30:

        if stop_event.is_set():
            return None

        if tunnel.poll() is not None:

            log(
                "[TUNEL] SSH encerrou durante a conexão."
            )

            return None

        try:

            text = tunnel.stdout.readline()

        except Exception:

            text = ""

        if not text:

            time.sleep(0.2)
            continue

        text = text.strip()

        if text:

            log(
                "[TUNEL] " + text
            )

        found = get_tunnel_url(text)

        if found:

            tunnel_url = found

            line()
            log("LINK DA TRANSMISSÃO")
            line()

            log(
                "LINK PRINCIPAL: "
                + tunnel_url
            )

            log(
                "LINK HLS: "
                + tunnel_url
                + "/live.m3u8"
            )

            line()

            return tunnel_url

    log(
        "[TUNEL] Timeout aguardando endereço."
    )

    try:

        if tunnel.poll() is None:
            tunnel.terminate()

    except Exception:
        pass

    tunnel = None

    return None


def monitor_tunnel():

    global tunnel
    global tunnel_url

    reconnect_delay = 5

    while not stop_event.is_set():

        time.sleep(5)

        if stop_event.is_set():
            break

        # ----------------------------------------------------
        # Verifica se o processo SSH ainda existe
        # ----------------------------------------------------

        if tunnel is not None:

            status = tunnel.poll()

            if status is None:
                continue

            log("")
            line()

            log(
                "[TUNEL] CONEXÃO SSH PERDIDA"
            )

            log(
                f"[TUNEL] Código de saída: {status}"
            )

            line()

        else:

            log(
                "[TUNEL] Nenhum túnel ativo."
            )

        tunnel = None

        # ----------------------------------------------------
        # Reconexão
        # ----------------------------------------------------

        while (
            not stop_event.is_set()
            and tunnel is None
        ):

            log(
                f"[TUNEL] Reconectando em "
                f"{reconnect_delay}s..."
            )

            time.sleep(
                reconnect_delay
            )

            if stop_event.is_set():
                break

            try:

                new_url = start_tunnel()

                if new_url:

                    tunnel_url = new_url

                    reconnect_delay = 5

                    line()

                    log(
                        "TÚNEL RESTABELECIDO"
                    )

                    line()

                    log(
                        "LINK PRINCIPAL:"
                    )

                    log(
                        tunnel_url
                    )

                    log(
                        "LINK HLS:"
                    )

                    log(
                        tunnel_url
                        + "/live.m3u8"
                    )

                    line()

                    break

                else:

                    log(
                        "[TUNEL] Falha na reconexão."
                    )

                    reconnect_delay = min(
                        reconnect_delay * 2,
                        30
                    )

            except Exception as e:

                log(
                    "[TUNEL] Erro na reconexão: "
                    + str(e)
                )

                reconnect_delay = min(
                    reconnect_delay * 2,
                    30
                )
