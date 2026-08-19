"""
Command-line interface for LiquidGlass Downloader.

Provides a simple CLI for batch downloading videos without the GUI.
"""
from __future__ import annotations
import argparse
import sys
import time
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .core.config import CONFIG
from .core.downloader import DownloadManager
from .core.db import DB_INSTANCE as DB
from .core.models import Status
from .core.validation import validate_urls, URLValidationError
from .core.constants import MIN_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_DOWNLOADS
from .core.startup import quick_startup, get_startup_info, initialize_application
from .core.logging_util import get_logger

console = Console()
log = get_logger("cli")


def main(argv=None):
    """
    Main entry point for CLI application.

    Args:
        argv: Optional command-line arguments (defaults to sys.argv)
    """
    p = argparse.ArgumentParser(
        description="LiquidGlass Downloader - Fast and elegant video downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://youtube.com/watch?v=VIDEO_ID
  %(prog)s URL1 URL2 URL3 -c 5
  %(prog)s https://youtube.com/playlist?list=PLAYLIST_ID -o ~/Videos
        """
    )
    p.add_argument(
        "urls",
        nargs="+",
        help="One or more video/playlist URLs to download"
    )
    p.add_argument(
        "-o", "--output",
        help="Download directory (overrides config)"
    )
    p.add_argument(
        "-f", "--format",
        default=None,
        help="Video quality/format (best, 1080p, 720p, 480p, audio)"
    )
    p.add_argument(
        "-c", "--concurrency",
        type=int,
        default=None,
        help=f"Concurrent downloads ({MIN_CONCURRENT_DOWNLOADS}-{MAX_CONCURRENT_DOWNLOADS})"
    )
    p.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip URL validation (use with caution)"
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    p.add_argument(
        "--skip-updates",
        action="store_true",
        help="Skip auto-updates on startup"
    )
    p.add_argument(
        "--version",
        action="store_true",
        help="Show version and platform information"
    )

    args = p.parse_args(argv)

    # Handle version request
    if args.version:
        info = get_startup_info()
        console.print(f"[cyan]LiquidGlass Downloader v{info.get('app_version', '2.3.0')}[/cyan]")
        platform = info.get("platform", {})
        console.print(f"Platform: {platform.get('system', 'unknown')}")
        console.print(f"Python: {platform.get('python_version', 'unknown')}")
        console.print(f"Architecture: {platform.get('architecture', 'unknown')}")
        return

    # Perform startup checks
    console.print("[cyan]Initializing...[/cyan]")
    if args.skip_updates:
        if not quick_startup():
            console.print("[red]Startup checks failed. Please check logs.[/red]")
            sys.exit(1)
    else:
        result = initialize_application(async_mode=False)
        if not result.success:
            console.print("[red]Startup checks failed:[/red]")
            for error in result.errors:
                console.print(f"  [red]✗[/red] {error}")
            sys.exit(1)

        if result.updates_performed:
            console.print("[green]Auto-updates completed:[/green]")
            for pkg, success in result.updates_performed.items():
                status = "✓" if success else "✗"
                console.print(f"  [{status}] {pkg}")
            console.print()

    # Validate URLs first
    if not args.no_validate:
        console.print("[cyan]Validating URLs...[/cyan]")
        valid_urls, errors = validate_urls(args.urls, check_platform=False)

        if errors:
            console.print("[yellow]Warning: Some URLs failed validation:[/yellow]")
            for error in errors:
                console.print(f"  [red]✗[/red] {error}")

        if not valid_urls:
            console.print("[red]Error: No valid URLs provided.[/red]")
            sys.exit(1)

        args.urls = valid_urls
        console.print(f"[green]✓[/green] {len(valid_urls)} valid URL(s)\n")

    # Apply configuration overrides
    if args.output:
        s = CONFIG.settings
        s.download_dir = args.output
        CONFIG.save(s)
        console.print(f"[cyan]Output directory:[/cyan] {args.output}")

    if args.concurrency:
        concurrency = max(MIN_CONCURRENT_DOWNLOADS, min(MAX_CONCURRENT_DOWNLOADS, args.concurrency))
        CONFIG.settings.concurrent_downloads = concurrency
        CONFIG.save(CONFIG.settings)
        console.print(f"[cyan]Concurrent downloads:[/cyan] {concurrency}")

    # Initialize download manager
    dm = DownloadManager()

    # Queue all URLs
    console.print(f"\n[cyan]Queuing {len(args.urls)} download(s)...[/cyan]")
    item_ids = []
    for url in args.urls:
        try:
            item_id = dm.queue(url, args.format)
            item_ids.append(item_id)
            console.print(f"  [green]✓[/green] Queued: {url[:60]}...")
        except URLValidationError as e:
            console.print(f"  [red]✗[/red] Failed: {e}")
        except Exception as e:
            console.print(f"  [red]✗[/red] Error: {str(e)}")

    if not item_ids:
        console.print("[red]No downloads queued. Exiting.[/red]")
        sys.exit(1)

    # Start all downloads
    console.print("\n[cyan]Starting downloads...[/cyan]\n")
    for item_id in item_ids:
        dm.start(item_id)

    # Monitor progress
    try:
        _monitor_downloads(item_ids, args.verbose)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Canceling downloads...[/yellow]")
        for item_id in item_ids:
            dm.cancel(item_id)
        sys.exit(130)
    finally:
        dm.cleanup()

    # Show summary
    _show_summary(item_ids)


def _monitor_downloads(item_ids: list[int], verbose: bool = False):
    """
    Monitor download progress and display status.

    Args:
        item_ids: List of database IDs to monitor
        verbose: Whether to show detailed progress
    """
    last_update = time.time()
    update_interval = 1.0  # Update every second

    while True:
        current_time = time.time()

        # Check if all downloads are complete
        rows = [DB.get(i) for i in item_ids]
        if all(r and r.status in (Status.COMPLETED, Status.ERROR, Status.CANCELED) for r in rows):
            break

        # Update display
        if verbose and (current_time - last_update >= update_interval):
            _display_status(rows)
            last_update = current_time

        time.sleep(0.5)


def _display_status(rows: list):
    """Display current download status."""
    console.clear()
    table = Table(title="Download Status")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Progress", style="green")

    for row in rows:
        if not row:
            continue

        title = row.title or "Fetching metadata..."
        status = row.status.upper()

        if row.total_bytes and row.downloaded_bytes:
            progress = f"{(row.downloaded_bytes / row.total_bytes * 100):.1f}%"
        else:
            progress = "..."

        table.add_row(str(row.id), title[:40], status, progress)

    console.print(table)


def _show_summary(item_ids: list[int]):
    """
    Show download summary.

    Args:
        item_ids: List of completed download IDs
    """
    rows = [DB.get(i) for i in item_ids]
    completed = sum(1 for r in rows if r and r.status == Status.COMPLETED)
    failed = sum(1 for r in rows if r and r.status == Status.ERROR)
    canceled = sum(1 for r in rows if r and r.status == Status.CANCELED)

    console.print("\n" + "="*60)
    console.print("[bold cyan]Download Summary[/bold cyan]")
    console.print("="*60)
    console.print(f"[green]Completed:[/green] {completed}")
    console.print(f"[red]Failed:[/red] {failed}")
    console.print(f"[yellow]Canceled:[/yellow] {canceled}")
    console.print(f"[cyan]Total:[/cyan] {len(item_ids)}")

    if failed > 0:
        console.print("\n[red]Failed downloads:[/red]")
        for row in rows:
            if row and row.status == Status.ERROR:
                console.print(f"  [red]✗[/red] {row.url}")
                if row.errmsg:
                    console.print(f"    [dim]{row.errmsg}[/dim]")

    console.print()


if __name__ == "__main__":
    main()
