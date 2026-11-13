import os


from crewai import LLM
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import (
	ScrapeWebsiteTool
)






@CrewBase
class ModularPaperTradingCryptoBotCrew:
    """ModularPaperTradingCryptoBot crew"""

    
    @agent
    def senior_python_crypto_bot_developer(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["senior_python_crypto_bot_developer"],
            
            
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
    def qa_test_engineer(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["qa_test_engineer"],
            
            
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
    def security_auditor(self) -> Agent:
        
        
        return Agent(
            config=self.agents_config["security_auditor"],
            
            
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
    def develop_crypto_bot_source_code(self) -> Task:
        return Task(
            config=self.tasks_config["develop_crypto_bot_source_code"],
            markdown=False,
            
            
        )
    
    @task
    def write_pytest_test_suite(self) -> Task:
        return Task(
            config=self.tasks_config["write_pytest_test_suite"],
            markdown=False,
            
            
        )
    
    @task
    def security_audit_and_final_deliverable(self) -> Task:
        return Task(
            config=self.tasks_config["security_audit_and_final_deliverable"],
            markdown=False,
            
            
        )
    

    @crew
    def crew(self) -> Crew:
        """Creates the ModularPaperTradingCryptoBot crew"""

        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,

            chat_llm=LLM(model="openai/gpt-5.6-luna"),
        )


