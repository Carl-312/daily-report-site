"""
Daily Report Site - Main Entry Point
Unified CLI for fetching news, summarizing, and building static site
"""
from __future__ import annotations
import argparse
import sys

from config import get_config
from sources import fetch_all, Article
from utils import dedupe, today_ymd, today_cn, save_json, save_markdown, load_json
from summarizer import summarize, offline_summary, test_connection


def cmd_run(args):
    """Full pipeline: fetch → summarize → build"""
    cfg = get_config()
    date_str = today_ymd()
    
    print(f"🚀 Daily Report - {date_str}")
    print("=" * 50)
    
    # 1. Fetch
    print("\n📡 Fetching news...")
    articles = fetch_all(
        enabled_sources=cfg.sources,
        max_articles=cfg.max_articles,
        syft_url=cfg.syft_web_app_url,
        syft_key=cfg.syft_secret_key,
    )
    
    # 2. Dedupe
    print(f"\n🔄 Deduplicating {len(articles)} articles...")
    articles = dedupe(articles)
    print(f"   Remaining: {len(articles)} unique articles")
    
    # 3. Save JSON
    articles_dict = [a.to_dict() if isinstance(a, Article) else a for a in articles]
    json_path = save_json(cfg.data_dir, date_str, {
        "date": date_str,
        "articles": articles_dict,
    })
    print(f"\n💾 Saved JSON: {json_path}")
    
    # 4. Summarize
    print("\n🤖 Generating summary...")
    if args.offline or not cfg.api_key:
        if not cfg.api_key:
            print("   ⚠️  No API key, using offline mode")
        content = offline_summary(articles_dict)
    else:
        content = summarize(articles_dict, stream=True)
    
    # 5. Build Markdown title
    title = f"🔥（{today_cn()}）每日AI资讯一览✨"
    full_content = f"{title}\n\n{content}"
    
    # 6. Save Markdown
    md_path = save_markdown(cfg.content_dir, date_str, full_content)
    print(f"\n📝 Saved Markdown: {md_path}")
    
    # 7. Build HTML
    print("\n🏗️  Building HTML site...")
    from build import build_site
    build_site()
    
    print("\n" + "=" * 50)
    print("✅ Done!")
    print(f"   Articles: {len(articles)}")
    print(f"   JSON: {json_path}")
    print(f"   Markdown: {md_path}")
    print(f"   HTML: {cfg.docs_dir}/")


def cmd_fetch(args):
    """Fetch only - save to JSON"""
    cfg = get_config()
    date_str = today_ymd()
    
    print(f"📡 Fetching news for {date_str}...")
    articles = fetch_all(
        enabled_sources=cfg.sources,
        max_articles=cfg.max_articles,
        syft_url=cfg.syft_web_app_url,
        syft_key=cfg.syft_secret_key,
    )
    
    articles = dedupe(articles)
    articles_dict = [a.to_dict() if isinstance(a, Article) else a for a in articles]
    
    json_path = save_json(cfg.data_dir, date_str, {
        "date": date_str,
        "articles": articles_dict,
    })
    
    print(f"✅ Saved {len(articles)} articles to {json_path}")


def cmd_summarize(args):
    """Summarize only - from existing JSON"""
    cfg = get_config()
    date_str = today_ymd()
    
    data = load_json(cfg.data_dir, date_str)
    if not data:
        print(f"❌ No data found for {date_str}")
        return
    
    articles = data.get("articles", [])
    print(f"🤖 Summarizing {len(articles)} articles...")
    
    if args.offline or not cfg.api_key:
        content = offline_summary(articles)
    else:
        content = summarize(articles, stream=True)
    
    title = f"🔥（{today_cn()}）每日AI资讯一览✨"
    full_content = f"{title}\n\n{content}"
    
    md_path = save_markdown(cfg.content_dir, date_str, full_content)
    print(f"✅ Saved to {md_path}")


def cmd_build(args):
    """Build HTML site only"""
    print("🏗️  Building HTML site...")
    from build import build_site
    build_site()


def cmd_test(args):
    """Test API connection"""
    test_connection()


def main():
    parser = argparse.ArgumentParser(
        description="Daily Report Site - AI News Aggregator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # run command
    p_run = subparsers.add_parser("run", help="Full pipeline: fetch → summarize → build")
    p_run.add_argument("--offline", action="store_true", help="Use offline summarization")
    p_run.set_defaults(func=cmd_run)
    
    # fetch command
    p_fetch = subparsers.add_parser("fetch", help="Fetch news only")
    p_fetch.set_defaults(func=cmd_fetch)
    
    # summarize command
    p_sum = subparsers.add_parser("summarize", help="Summarize from existing JSON")
    p_sum.add_argument("--offline", action="store_true", help="Use offline summarization")
    p_sum.set_defaults(func=cmd_summarize)
    
    # build command
    p_build = subparsers.add_parser("build", help="Build HTML site only")
    p_build.set_defaults(func=cmd_build)
    
    # test command
    p_test = subparsers.add_parser("test", help="Test API connection")
    p_test.set_defaults(func=cmd_test)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
