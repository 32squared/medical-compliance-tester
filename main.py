#!/usr/bin/env python3
"""
나만의 주치의 — 의료법 준수 자동화 테스트 도구
==============================================

사용법:
  # Mock 데이터로 데모 실행
  python main.py --mode mock

  # 실제 SKIX API 대상 테스트 (dev 환경)
  python main.py --mode live --env dev --api-key YOUR_KEY --uid YOUR_UID

  # stg 환경, 특정 카테고리만
  python main.py --mode live --env stg --api-key KEY --uid UID --category "진단 유도"

  # 결과를 특정 경로에 저장
  python main.py --mode mock --output ./my_report.html
"""

import argparse
import os
import sys

import config as cfg
from scenarios import SCENARIOS, get_scenarios_by_category, get_categories
from analyzer import ComplianceAnalyzer
from runner import TestRunner, MockTestRunner
from dashboard import DashboardGenerator


def main():
    parser = argparse.ArgumentParser(
        description="나만의 주치의 — 의료법 준수 자동화 테스트 도구"
    )
    parser.add_argument(
        "--mode", choices=["live", "mock"], default="mock",
        help="실행 모드: live(실제 API) 또는 mock(샘플 응답) [기본: mock]"
    )
    parser.add_argument(
        "--env", choices=["dev", "stg", "prod"], default="dev",
        help="API 환경 [기본: dev]"
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="X-API-Key 값"
    )
    parser.add_argument(
        "--uid", type=str, default=None,
        help="X-Api-UID 값 (사용자 식별)"
    )
    parser.add_argument(
        "--source-types", type=str, default="WEB,PUBMED",
        help="검색 소스 (쉼표 구분) [기본: WEB,PUBMED]"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help=f"테스트할 카테고리 (선택사항). 가능한 값: {get_categories()}"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="리포트 HTML 저장 경로 [기본: ./reports/report_YYYYMMDD_HHMMSS.html]"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="콘솔 출력 최소화"
    )

    args = parser.parse_args()

    # 환경 설정
    cfg.ACTIVE_ENV = args.env

    # 인증 설정
    if args.api_key:
        cfg.API_CONFIG["x_api_key"] = args.api_key
    if args.uid:
        cfg.API_CONFIG["x_api_uid"] = args.uid

    # 소스 타입 설정
    cfg.API_CONFIG["source_types"] = [
        s.strip().upper() for s in args.source_types.split(",")
    ]

    # 시나리오 선택
    if args.category:
        scenarios = get_scenarios_by_category(args.category)
        if not scenarios:
            print(f"❌ 카테고리 '{args.category}'를 찾을 수 없습니다.")
            print(f"   가능한 카테고리: {get_categories()}")
            sys.exit(1)
    else:
        scenarios = SCENARIOS

    # Runner 선택
    if args.mode == "mock":
        runner = MockTestRunner()
        print("📋 Mock 모드로 실행합니다 (샘플 응답 사용)")
    else:
        runner = TestRunner()
        env_info = cfg.ENVIRONMENTS[cfg.ACTIVE_ENV]
        print(f"🔗 Live 모드 — {cfg.ACTIVE_ENV.upper()} 환경")
        print(f"   URL: {cfg.get_api_url()}")
        print(f"   Tenant: {env_info['x_tenant_domain']}")

        if not cfg.API_CONFIG["x_api_key"]:
            print("⚠️  경고: X-API-Key가 설정되지 않았습니다. --api-key 옵션을 확인하세요.")

    # 리포트 디렉토리 생성
    output_path = args.output
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    else:
        os.makedirs(cfg.REPORT_CONFIG["output_dir"], exist_ok=True)

    # 테스트 실행
    suite_result = runner.run_all(scenarios=scenarios, verbose=not args.quiet)

    # 대시보드 생성
    generator = DashboardGenerator()
    report_path = generator.generate(suite_result, output_path=output_path)
    print(f"\n📊 리포트 생성 완료: {report_path}")

    # 종료 코드: 실패가 있으면 1
    sys.exit(0 if suite_result.failed_count == 0 else 1)


if __name__ == "__main__":
    main()
