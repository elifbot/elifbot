import os


from crewai import LLM
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import (
	ScrapeWebsiteTool,
	URLReadTool
)






@CrewBase
class BinanceOkxPaperFuturesBotCrew:
    """BinanceOkxPaperFuturesBot crew"""

    
    @agent
    def senior_python_futures_bot_developer(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["senior_python_futures_bot_developer"],
            
            
            tools=[				ScrapeWebsiteTool()],
            
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            
            
            max_execution_time=None,
            llm=LLM(
                model="openai/gpt-5.6-luna",
                
                
            ),
            
        )
        
    
    @agent
    def qa_test_engineer___futures_bot(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["qa_test_engineer___futures_bot"],
            
            
            tools=[],
            
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            
            
            max_execution_time=None,
            llm=LLM(
                model="openai/gpt-5.6-luna",
                
                
            ),
            
        )
        
    
    @agent
    def security_auditor_and_deliverable_integrator(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["security_auditor_and_deliverable_integrator"],
            
            
            tools=[],
            
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            
            
            max_execution_time=None,
            llm=LLM(
                model="openai/gpt-5.6-luna",
                
                
            ),
            
        )
        
    
    @agent
    def market_data_exchange_research_specialist(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["market_data_exchange_research_specialist"],
            
            
            tools=[				ScrapeWebsiteTool(),
				URLReadTool()],
            
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            
            
            max_execution_time=None,
            llm=LLM(
                model="openai/gpt-5.6-luna",
                
                
            ),
            
        )
        
    
    @agent
    def backtest_statistical_validation_analyst(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["backtest_statistical_validation_analyst"],
            
            
            tools=[],
            
            reasoning=False,
            max_reasoning_attempts=None,
            inject_date=True,
            allow_delegation=False,
            max_iter=25,
            max_rpm=None,
            
            
            max_execution_time=None,
            llm=LLM(
                model="openai/gpt-5.6-luna",
                
                
            ),
            
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
        """Creates the BinanceOkxPaperFuturesBot crew"""

        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,

            chat_llm=LLM(model="openai/gpt-5.6-luna"),
        )


