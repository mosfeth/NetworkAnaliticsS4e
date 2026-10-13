from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from .config import ConfigError, load_settings, ensure_runtime_files, public_dict
from .diary import Diary
from .monitor import MonitorService
from .queue import LocalQueue
from .scheduler import SchedulerError
from .supabase_repository import SupabaseRepository


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="supadiag", description="SupaDiag - Monitoramento de rede")
    subparsers = parser.add_subparsers(dest="command", required=False)

    # check
    subparsers.add_parser("check", help="Verifica conexão com Supabase")

    # schema
    subparsers.add_parser("schema", help="Mostra caminho do script SQL de migração")

    # client
    client_parser = subparsers.add_parser("client", help="Gerencia clientes")
    client_sub = client_parser.add_subparsers(dest="client_action", required=True)
    add_client = client_sub.add_parser("add", help="Adiciona cliente")
    add_client.add_argument("--name", required=True, help="Nome do cliente")
    list_client = client_sub.add_parser("list", help="Lista clientes")
    update_client = client_sub.add_parser("update", help="Atualiza cliente")
    update_client.add_argument("--id", required=True, help="ID do cliente")
    update_client.add_argument("--name", required=True, help="Novo nome")
    delete_client = client_sub.add_parser("delete", help="Remove cliente")
    delete_client.add_argument("--id", required=True, help="ID do cliente")

    # machine
    machine_parser = subparsers.add_parser("machine", help="Gerencia máquinas")
    machine_sub = machine_parser.add_subparsers(dest="machine_action", required=True)
    add_machine = machine_sub.add_parser("add", help="Adiciona máquina")
    add_machine.add_argument("--client-id", required=True, help="ID do cliente")
    add_machine.add_argument("--tag", required=True, help="Tag da máquina")
    add_machine.add_argument("--ip", required=True, help="IP da máquina")
    add_machine.add_argument("--frequency", type=int, required=True, help="Frequência em segundos")
    list_machine = machine_sub.add_parser("list", help="Lista máquinas")
    list_machine.add_argument("--client-id", help="Filtrar por cliente")
    list_machine.add_argument("--active-only", action="store_true", help="Apenas ativas")
    update_machine = machine_sub.add_parser("update", help="Atualiza máquina")
    update_machine.add_argument("--id", required=True, help="ID da máquina")
    update_machine.add_argument("--tag", help="Nova tag")
    update_machine.add_argument("--ip", help="Novo IP")
    update_machine.add_argument("--frequency", type=int, help="Nova frequência")
    update_machine.add_argument("--active", type=lambda x: x.lower() == "true", help="Ativo (true/false)")
    delete_machine = machine_sub.add_parser("delete", help="Remove máquina")
    delete_machine.add_argument("--id", required=True, help="ID da máquina")

    # monitor
    monitor_parser = subparsers.add_parser("monitor", help="Executa monitoramento")
    monitor_parser.add_argument("--once", action="store_true", help="Executa apenas um ciclo")
    monitor_parser.add_argument("--cycles", type=int, help="Número de ciclos (infinito se omitido)")

    # service
    service_parser = subparsers.add_parser("service", help="Gerencia serviço do Agendador de Tarefas")
    service_sub = service_parser.add_subparsers(dest="service_action", required=True)
    service_sub.add_parser("install", help="Instala tarefa no Agendador")
    service_sub.add_parser("status", help="Status da tarefa")
    service_sub.add_parser("restart", help="Reinicia a tarefa")
    service_sub.add_parser("remove", help="Remove tarefa")

    # diary
    diary_parser = subparsers.add_parser("diary", help="Mostra o diário (memory.txt)")
    diary_parser.add_argument("--lines", type=int, default=50, help="Últimas N linhas")
    
    # traceroute
    traceroute_parser = subparsers.add_parser("traceroute", help="Executa traceroute para uma máquina")
    traceroute_parser.add_argument("--machine-id", required=True, help="ID da máquina")
    
    # ml-train
    ml_train_parser = subparsers.add_parser("ml-train", help="Treina modelo LSTM para uma máquina")
    ml_train_parser.add_argument("--machine-id", required=True, help="ID da máquina")
    ml_train_parser.add_argument("--epochs", type=int, default=50, help="Número de épocas")
    ml_train_parser.add_argument("--batch-size", type=int, default=8, help="Tamanho do batch")
    ml_train_parser.add_argument("--limit", type=int, default=5000, help="Limite de medições")
    ml_train_parser.add_argument("--output", default="models", help="Diretório de saída")
    
    # app (interactive)
    subparsers.add_parser("app", help="Inicia interface interativa (Textual)")

    return parser


def load_app() -> tuple[Settings, Diary, SupabaseRepository, LocalQueue]:
    settings = load_settings()
    ensure_runtime_files(settings)
    diary = Diary(settings.memory_file)
    repo = SupabaseRepository(settings)
    queue = LocalQueue(settings.queue_file)
    return settings, diary, repo, queue


def cmd_check(args: argparse.Namespace) -> int:
    settings, diary, repo, _ = load_app()
    ok, msg = repo.health_check()
    print(f"Supabase: {'OK' if ok else 'FALHA'} - {msg}")
    diary.log("CHECK", msg, {"ok": ok})
    return 0 if ok else 1


def cmd_schema(args: argparse.Namespace) -> int:
    path = Path(__file__).resolve().parents[2] / "sql" / "001_schema.sql"
    print(f"Script de migração: {path}")
    if path.exists():
        print(path.read_text(encoding="utf-8"))
    else:
        print("Arquivo não encontrado.")
    return 0


def cmd_client(args: argparse.Namespace) -> int:
    settings, diary, repo, _ = load_app()
    if args.client_action == "add":
        client = repo.create_client(args.name)
        print(f"Cliente criado: {client.id} - {client.name}")
        diary.log("CLIENTE_CRIADO", client.name, {"client_id": client.id})
    elif args.client_action == "list":
        clients = repo.list_clients()
        for c in clients:
            print(f"{c.id} | {c.name} | {c.created_at}")
    elif args.client_action == "update":
        client = repo.update_client(args.id, args.name)
        print(f"Cliente atualizado: {client.id} - {client.name}")
        diary.log("CLIENTE_ATUALIZADO", client.name, {"client_id": client.id})
    elif args.client_action == "delete":
        repo.delete_client(args.id)
        print(f"Cliente {args.id} removido")
        diary.log("CLIENTE_REMOVIDO", "Cliente removido", {"client_id": args.id})
    return 0


def cmd_machine(args: argparse.Namespace) -> int:
    settings, diary, repo, _ = load_app()
    if args.machine_action == "add":
        machine = repo.create_machine(args.client_id, args.tag, args.ip, args.frequency)
        print(f"Máquina criada: {machine.id} - {machine.tag} ({machine.ip})")
        diary.log("MAQUINA_CRIADA", machine.tag, {"machine_id": machine.id, "client_id": machine.client_id})
    elif args.machine_action == "list":
        machines = repo.list_machines(client_id=args.client_id, active_only=args.active_only)
        for m in machines:
            print(f"{m.id} | {m.client_id} | {m.tag} | {m.ip} | {m.frequency_seconds}s | {'ativa' if m.active else 'inativa'}")
    elif args.machine_action == "update":
        machine = repo.update_machine(
            args.id,
            tag=args.tag,
            ip=args.ip,
            frequency_seconds=args.frequency,
            active=args.active,
        )
        print(f"Máquina atualizada: {machine.id} - {machine.tag}")
        diary.log("MAQUINA_ATUALIZADA", machine.tag, {"machine_id": machine.id})
    elif args.machine_action == "delete":
        repo.delete_machine(args.id)
        print(f"Máquina {args.id} removida")
        diary.log("MAQUINA_REMOVIDA", "Máquina removida", {"machine_id": args.id})
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    settings, diary, repo, queue = load_app()
    monitor = MonitorService(settings, repo, queue, diary)
    if args.once:
        asyncio.run(monitor.run_cycle())
    else:
        cycles = args.cycles
        async def run():
            for _ in range(cycles) if cycles else iter(int, 1):
                if monitor._stop.is_set():
                    break
                await monitor.run_cycle()
                await asyncio.sleep(1)
        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            print("Monitor interrompido")
    return 0


def cmd_service(args: argparse.Namespace) -> int:
    settings, diary, _, _ = load_app()
    from .scheduler import WindowsScheduler
    scheduler = WindowsScheduler(settings)
    if args.service_action == "install":
        max_retries = 3
        for attempt in range(max_retries):
            try:
                status = scheduler.install()
                print(f"Tarefa instalada: {status.installed}")
                print(status.output)
                diary.log("SERVICO_INSTALADO", "Tarefa agendada criada")
                break
            except SchedulerError as exc:
                if attempt < max_retries - 1:
                    print(f"Tentativa {attempt + 1} falhou: {exc}. Tentando novamente em 2 segundos...")
                    time.sleep(2)
                else:
                    raise
    elif args.service_action == "status":
        status = scheduler.status()
        print(f"Instalada: {status.installed}")
        print(status.output)
    elif args.service_action == "restart":
        max_retries = 3
        for attempt in range(max_retries):
            try:
                status = scheduler.restart()
                print(f"Tarefa reiniciada: {status.installed}")
                print(status.output)
                diary.log("SERVICO_REINICIADO", "Tarefa agendada reiniciada")
                break
            except SchedulerError as exc:
                if attempt < max_retries - 1:
                    print(f"Tentativa {attempt + 1} falhou: {exc}. Tentando novamente em 2 segundos...")
                    time.sleep(2)
                else:
                    raise
    elif args.service_action == "remove":
        scheduler.remove()
        print("Tarefa removida")
        diary.log("SERVICO_REMOVIDO", "Tarefa agendada removida")
    return 0


def cmd_diary(args: argparse.Namespace) -> int:
    settings, diary, _, _ = load_app()
    lines = args.lines
    if settings.memory_file.exists():
        content = settings.memory_file.read_text(encoding="utf-8").strip().splitlines()
        for line in content[-lines:]:
            print(line)
    else:
        print("Diário vazio.")
    return 0


def cmd_traceroute(args: argparse.Namespace) -> int:
    settings, diary, repo, _ = load_app()
    machine_id = args.machine_id
    machine = repo.get_machine(machine_id)
    if not machine:
        print(f"Máquina não encontrada: {machine_id}")
        return 1
    
    print(f"Executando traceroute para {machine.tag} ({machine.ip})...")
    from .traceroute import run_traceroute
    result = run_traceroute(machine.ip)
    print(f"Total hops: {result.total_hops}")
    print(f"Destino alcançado: {result.destination_reached}")
    
    try:
        repo.save_traceroute(result, machine.client_id, machine.id)
        diary.log(
            "TRACEROUTE_OK",
            f"Traceroute manual {machine.tag} ({machine.ip})",
            {"machine_id": machine.id, "total_hops": result.total_hops},
        )
        print("Traceroute salvo com sucesso.")
    except Exception as exc:
        diary.log(
            "TRACEROUTE_ERRO_ENVIO",
            f"Falha ao salvar traceroute {machine.tag}",
            {"error": str(exc)},
        )
        print(f"Erro ao salvar: {exc}")
    return 0


def cmd_ml_train(args: argparse.Namespace) -> int:
    """Treina modelo LSTM para uma máquina específica."""
    settings, diary, repo, _ = load_app()
    machine_id = args.machine_id
    machine = repo.get_machine(machine_id)
    if not machine:
        print(f"Máquina não encontrada: {machine_id}")
        return 1
    
    print(f"Treinando modelo LSTM para {machine.tag} ({machine.ip})")
    print(f"Épocas: {args.epochs}, Batch: {args.batch_size}, Limit: {args.limit}")
    
    from .ml_trainer import NetworkQualityTrainer
    trainer = NetworkQualityTrainer(settings, repo)
    
    try:
        result = trainer.train(
            machine_id=machine_id,
            epochs=args.epochs,
            batch_size=args.batch_size,
            limit=args.limit,
        )
        print(f"\n✅ Treino concluído!")
        print(f"  Épocas treinadas: {result.epochs_trained}")
        print(f"  Acurácia teste: {result.accuracy:.2%}")
        print(f"  F1-score: {result.f1_score:.2%}")
        print(f"  Acurácia validação: {result.val_accuracy:.2%}")
        print(f"  Melhor validação loss: {result.best_val_loss:.4f}")
        
        # Salva modelo
        from pathlib import Path
        output_dir = Path(args.output)
        if not output_dir.is_absolute():
            output_dir = settings.project_root / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / f"model_{machine_id[:8]}.pth"
        import torch
        if trainer.model is None:
            raise RuntimeError("O treinamento terminou sem produzir um modelo.")
        torch.save(
            {
                "state_dict": trainer.model.state_dict(),
                "scaler_mean": trainer.scaler.mean_.tolist(),
                "scaler_scale": trainer.scaler.scale_.tolist(),
                "machine_id": machine_id,
                "trained_at": result.trained_at,
            },
            model_path,
        )
        print(f"\n💾 Modelo salvo em: {model_path}")
        
        # Salva métricas
        metrics_path = output_dir / f"metrics_{machine_id[:8]}.json"
        metrics_data = {
            "accuracy": result.accuracy,
            "f1_score": result.f1_score,
            "val_accuracy": result.val_accuracy,
            "val_f1": result.val_f1,
            "epochs_trained": result.epochs_trained,
            "best_val_loss": result.best_val_loss,
            "trained_at": result.trained_at,
            "machine_id": machine_id,
        }
        with open(metrics_path, "w") as f:
            json.dump(metrics_data, f, indent=2)
        print(f"📊 Métricas salvas em: {metrics_path}")
        
        diary.log(
            "ML_TRAIN_OK",
            f"Treino concluído para {machine.tag}",
            {"machine_id": machine_id, "accuracy": result.accuracy},
        )
        return 0
    except Exception as exc:
        diary.log(
            "ML_TRAIN_ERRO",
            f"Falha no treino para {machine.tag}",
            {"machine_id": machine_id, "error": str(exc)},
        )
        print(f"\n❌ Erro no treino: {exc}")
        return 1


def cmd_app(args: argparse.Namespace) -> int:
    from .tui import SupaDiagApp
    settings, diary, repo, queue = load_app()
    app = SupaDiagApp(settings, diary, repo, queue)
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        # default to interactive app
        return cmd_app(args)
    command_map = {
        "check": cmd_check,
        "schema": cmd_schema,
        "client": cmd_client,
        "machine": cmd_machine,
        "monitor": cmd_monitor,
        "service": cmd_service,
        "diary": cmd_diary,
        "traceroute": cmd_traceroute,
        "ml-train": cmd_ml_train,
        "app": cmd_app,
    }
    handler = command_map.get(args.command)
    if not handler:
        parser.print_help()
        return 1
    try:
        return handler(args)
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}")
        return 2
    except Exception as exc:
        print(f"Erro inesperado: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
