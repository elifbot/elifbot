"""
crew.py — BinanceOkxPaperFuturesBot Crew tanımı.

NOT: Bu proje bir CREW iskeletidir; botun kendisi `../futures_bot/` altındadır.
Ajanlar artık "Dosya Yazıcı" aracı ile gerçek dosya üretir (önceki sürümde
tüm çıktı düz metin olarak dökülüyordu ve ZIP'e dönüşmüyordu).
"""
from crewai import LLM
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import ScrapeWebsiteTool, URLReadTool

from binance_okx_paper_futures_bot.tools.file_writer import FileWriterTool

# Model adı ortamdan bağımsız tutulur; kendi sağlayıcınıza göre değiştirin.
# Örn. "openai/gpt-4o-mini", "anthropic/claude-sonnet-4-5" vb.
MODEL = "openai/gpt-4o-mini"


@CrewBase
class BinanceOkxPaperFuturesBotCrew:
    """Paper-only vadeli işlem araştırma botu üretim crew'i."""

    @agent
    def senior_python_futures_bot_developer(self) -> Agent:
        return Agent(
            config=self.agents_config["senior_python_futures_bot_developer"],
            tools=[ScrapeWebsiteTool(), FileWriterTool()],
            reasoning=False,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            llm=LLM(model=MODEL),
        )

    @agent
    def qa_test_engineer___futures_bot(self) -> Agent:
        return Agent(
            config=self.agents_config["qa_test_engineer___futures_bot"],
            tools=[FileWriterTool()],
            reasoning=False,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            llm=LLM(model=MODEL),
        )

    @agent
    def security_auditor_and_deliverable_integrator(self) -> Agent:
        return Agent(
            config=self.agents_config["security_auditor_and_deliverable_integrator"],
            tools=[FileWriterTool()],
            reasoning=False,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            llm=LLM(model=MODEL),
        )

    @agent
    def market_data_exchange_research_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["market_data_exchange_research_specialist"],
            tools=[ScrapeWebsiteTool(), URLReadTool(), FileWriterTool()],
            reasoning=False,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            llm=LLM(model=MODEL),
        )

    @agent
    def backtest_statistical_validation_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["backtest_statistical_validation_analyst"],
            tools=[FileWriterTool()],
            reasoning=False,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            llm=LLM(model=MODEL),
        )

    @task
    def research_exchange_apis_and_open_source_bot_references(self) -> Task:
        return Task(
            config=self.tasks_config["research_exchange_apis_and_open_source_bot_references"],
            markdown=False,
        )

    @task
    def develop_multi_indicator_research_bot_source_code(self) -> Task:
        return Task(
            config=self.tasks_config["develop_multi_indicator_research_bot_source_code"],
            markdown=False,
        )

    @task
    def design_backtest_framework_and_statistical_validation(self) -> Task:
        return Task(
            config=self.tasks_config["design_backtest_framework_and_statistical_validation"],
            markdown=False,
        )

    @task
    def write_multi_indicator_bot_pytest_test_suite(self) -> Task:
        return Task(
            config=self.tasks_config["write_multi_indicator_bot_pytest_test_suite"],
            markdown=False,
        )

    @task
    def security_audit_and_final_deliverable_assembly(self) -> Task:
        return Task(
            config=self.tasks_config["security_audit_and_final_deliverable_assembly"],
            markdown=False,
        )

    @crew
    def crew(self) -> Crew:
        """Sequential crew: araştırma → kod → backtest → test → denetim."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            chat_llm=LLM(model=MODEL),
        )
