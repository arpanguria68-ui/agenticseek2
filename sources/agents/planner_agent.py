import json
from typing import List, Tuple, Type, Dict
from sources.utility import pretty_print, animate_thinking
from sources.agents.agent import Agent
from sources.agents.code_agent import CoderAgent
from sources.agents.file_agent import FileAgent
from sources.agents.browser_agent import BrowserAgent
from sources.agents.casual_agent import CasualAgent
from sources.text_to_speech import Speech
from sources.tools.tools import Tools
from sources.logger import Logger
from sources.memory import Memory


class PlannerAgent(Agent):
    def __init__(self, name, prompt_path, provider, verbose=False, browser=None):
        """
        The planner agent is a special agent that divides and conquers the task.
        """
        super().__init__(name, prompt_path, provider, verbose, None)
        self.tools = {"json": Tools()}
        self.tools["json"].tag = "json"
        self.browser = browser
        self.agents = {
            "coder": CoderAgent(
                name, "prompts/base/coder_agent.txt", provider, verbose=False
            ),
            "file": FileAgent(
                name, "prompts/base/file_agent.txt", provider, verbose=False
            ),
            "web": BrowserAgent(
                name,
                "prompts/base/browser_agent.txt",
                provider,
                verbose=False,
                browser=browser,
            ),
            "casual": CasualAgent(
                name, "prompts/base/casual_agent.txt", provider, verbose=False
            ),
        }
        self.role = "planification"
        self.type = "planner_agent"
        self.memory = Memory(
            self.load_prompt(prompt_path),
            recover_last_session=False,  # session recovery in handled by the interaction class
            memory_compression=False,
            model_provider=provider.get_model_name(),
        )
        self.logger = Logger("planner_agent.log")

    def get_task_names(self, text: str) -> List[str]:
        """
        Extracts task names from the given text.
        This method processes a multi-line string, where each line may represent a task name.
        containing '##' or starting with a digit. The valid task names are collected and returned.
        Args:
            text (str): A string containing potential task titles (eg: Task 1: I will...).
        Returns:
            List[str]: A list of extracted task names that meet the specified criteria.
        """
        tasks_names = []
        lines = text.strip().split("\n")
        for line in lines:
            if line is None:
                continue
            line = line.strip()
            if len(line) == 0:
                continue
            if "##" in line or line[0].isdigit():
                tasks_names.append(line)
                continue
        self.logger.info(f"Found {len(tasks_names)} tasks names.")
        return tasks_names

    def parse_agent_tasks(self, text: str) -> List[Tuple[str, str]]:
        """
        Parses agent tasks from the given LLM text.
        This method extracts task information from a JSON. It identifies task names and their details.
        Args:
            text (str): The input text containing task information in a JSON-like format.
        Returns:
            List[Tuple[str, str]]: A list of tuples containing task names and their details.
        """
        tasks = []
        tasks_names = self.get_task_names(text)

        self.logger.info(f"Raw plan text from LLM:\n{text}")

        import ast

        try:
            blocks, _ = self.tools["json"].load_exec_block(text)
            if not blocks:
                # Fallback: try to find the start and end of the JSON object
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end != -1:
                    json_str = text[start:end]
                    blocks = [json_str]
                else:
                    blocks = (
                        []
                    )  # Set to empty list to trigger text-based fallback later

            for block in blocks:
                try:
                    clean_block = (
                        block.replace("```json", "").replace("```", "").strip()
                    )
                    self.logger.info(
                        f"Attempting to parse block: {clean_block[:200]}..."
                    )

                    try:
                        line_json = json.loads(clean_block)
                    except json.JSONDecodeError:
                        self.logger.warning(
                            "JSON decode failed, attempting ast.literal_eval."
                        )
                        try:
                            line_json = ast.literal_eval(clean_block)
                        except Exception:
                            raise json.JSONDecodeError(
                                "Both JSON and AST failed", clean_block, 0
                            )

                    if "plan" in line_json:
                        for task in line_json["plan"]:
                            agent_name = task.get("agent", "").lower()
                            valid_agents = [k.lower() for k in self.agents.keys()]
                            if agent_name == "planner":
                                agent_name = "casual"
                            if agent_name not in valid_agents:
                                self.logger.warning(
                                    f"Agent {task.get('agent')} does not exist. mapping to casual."
                                )
                                task["agent"] = "Casual"
                            try:
                                agent = {
                                    "agent": task.get("agent", "Casual"),
                                    "id": task.get("id", str(len(tasks) + 1)),
                                    "task": task["task"],
                                }
                                if "need" in task:
                                    agent["need"] = task["need"]
                                tasks.append(agent)
                            except Exception:
                                continue
                except Exception as e:
                    self.logger.error(f"Parsing error for block: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error parsing agent tasks: {e}")

        self.logger.info(
            f"Debug: JSON parsing finished. Parsed tasks: {len(tasks)}, Text tasks detected: {len(tasks_names)}"
        )

        # Fallback: If JSON parsing failed to yield any tasks but we found text tasks
        if len(tasks) == 0 and len(tasks_names) > 0:
            self.logger.warning(
                "JSON parsing failed. Constructing plan from text tasks."
            )
            pretty_print(
                "JSON parsing failed. Constructing plan from text tasks.",
                color="warning",
            )
            for i, task_name in enumerate(tasks_names):
                agent_type = "Casual"
                t_lower = task_name.lower()
                if "code" in t_lower or "script" in t_lower or "python" in t_lower:
                    agent_type = "Coder"
                elif "search" in t_lower or "web" in t_lower or "internet" in t_lower:
                    agent_type = "Web"
                elif "file" in t_lower or "folder" in t_lower:
                    agent_type = "File"

                tasks.append(
                    {
                        "agent": agent_type,
                        "id": str(i + 1),
                        "task": task_name,
                        "need": [str(i)] if i > 0 else [],
                    }
                )

        if len(tasks_names) != len(tasks) and len(tasks_names) > 0 and len(tasks) > 0:
            # mismatch between header tasks and json tasks, usually fine to ignore
            pass

        # Create result in expected format
        result = []
        for t in tasks:
            result.append([t["task"], t])

        return result

    def make_prompt(self, task: str, agent_infos_dict: dict) -> str:
        """
        Generates a prompt for the agent based on the task and previous agents work information.
        Args:
            task (str): The task to be performed.
            agent_infos_dict (dict): A dictionary containing information from other agents.
        Returns:
            str: The formatted prompt for the agent.
        """
        infos = ""
        if agent_infos_dict is None or len(agent_infos_dict) == 0:
            infos = "No needed informations."
        else:
            for agent_id, info in agent_infos_dict.items():
                infos += f"\t- According to agent {agent_id}:\n{info}\n\n"
        prompt = f"""
        You are given informations from your AI friends work:
        {infos}
        Your task is:
        {task}
        """
        self.logger.info(f"Prompt for agent:\n{prompt}")
        return prompt

    def show_plan(self, agents_tasks: List[dict], answer: str) -> None:
        """
        Displays the plan made by the agent.
        Args:
            agents_tasks (dict): The tasks assigned to each agent.
            answer (str): The answer from the LLM.
        """
        if agents_tasks == []:
            pretty_print(answer, color="warning")
            pretty_print(
                "Failed to make a plan. This can happen with (too) small LLM. Clarify your request and insist on it making a plan within ```json.",
                color="failure",
            )
            return
        pretty_print("\n▂▘ P L A N ▝▂", color="status")
        for task_name, task in agents_tasks:
            pretty_print(f"{task['agent']} -> {task['task']}", color="info")
        pretty_print("▔▗ E N D ▖▔", color="status")

    async def make_plan(self, prompt: str) -> str:
        """
        Asks the LLM to make a plan.
        Args:
            prompt (str): The prompt to be sent to the LLM.
        Returns:
            str: The plan made by the LLM.
        """
        ok = False
        answer = None
        retries = 0
        max_retries = 3
        while not ok and retries < max_retries:
            retries += 1
            animate_thinking("Thinking...", color="status")
            self.memory.push("user", prompt)
            answer, reasoning = await self.llm_request()
            if "NO_UPDATE" in answer:
                return []
            agents_tasks = self.parse_agent_tasks(answer)
            if agents_tasks == []:
                self.show_plan(agents_tasks, answer)
                prompt = f"Failed to parse the tasks. Please write down your task followed by a json plan within ```json. Do not ask for clarification.\n"
                pretty_print(
                    f"Failed to make plan. Retrying ({retries}/{max_retries})...",
                    color="warning",
                )
                continue
            self.show_plan(agents_tasks, answer)
            ok = True

        if not ok:
            pretty_print(
                "Failed to generate a valid plan after multiple attempts.",
                color="failure",
            )
            self.logger.error(
                "Failed to generate a valid plan after multiple attempts."
            )
            return []

        self.logger.info(f"Plan made:\n{answer}")
        return self.parse_agent_tasks(answer)

    async def update_plan(
        self,
        goal: str,
        agents_tasks: List[dict],
        agents_work_result: dict,
        id: str,
        success: bool,
    ) -> dict:
        """
        Updates the plan with the results of the agents work.
        Args:
            goal (str): The goal to be achieved.
            agents_tasks (list): The tasks assigned to each agent.
            agents_work_result (dict): The results of the agents work.
        Returns:
            dict: The updated plan.
        """
        self.status_message = "Updating plan..."
        last_agent_work = agents_work_result[id]
        tool_success_str = "success" if success else "failure"
        pretty_print(
            f"Agent {id} work {tool_success_str}.",
            color="success" if success else "failure",
        )
        try:
            id_int = int(id)
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Invalid task ID '{id}': {e}. Skipping plan update.")
            return agents_tasks
        if id_int == len(agents_tasks):
            next_task = "No task follow, this was the last step. If it failed add a task to recover."
        else:
            try:
                next_task = f"Next task is: {agents_tasks[id_int][0]}."
            except (IndexError, KeyError):
                next_task = "No next task found."
        # if success:
        #    return agents_tasks # we only update the plan if last task failed, for now
        update_prompt = f"""
        Your goal is : {goal}
        You previously made a plan, agents are currently working on it.
        The last agent working on task: {id}, did the following work:
        {last_agent_work}
        Agent {id} work was a {tool_success_str} according to system interpreter.
        {next_task}
        Is the work done for task {id} leading to success or failure ? Did an agent fail with a task?
        If agent work was good: answer "NO_UPDATE"
        If agent work is leading to failure: update the plan.
        If a task failed add a task to try again or recover from failure. You might have near identical task twice.
        plan should be within ```json like before.
        You need to rewrite the whole plan, but only change the tasks after task {id}.
        Make the plan the same length as the original one or with only one additional step.
        Do not change past tasks. Change next tasks.
        """
        pretty_print("Updating plan...", color="status")
        plan = await self.make_plan(update_prompt)
        if plan == []:
            pretty_print("No plan update required.", color="info")
            return agents_tasks
        self.logger.info(f"Plan updated:\n{plan}")
        return plan

    async def start_agent_process(self, task: dict, required_infos: dict | None) -> str:
        """
        Starts the agent process for a given task.
        Args:
            task (dict): The task to be performed.
            required_infos (dict | None): The required information for the task.
        Returns:
            str: The result of the agent process.
        """
        self.status_message = f"Starting task {task['task']}..."
        agent_prompt = self.make_prompt(task["task"], required_infos)
        pretty_print(f"Agent {task['agent']} started working...", color="status")
        self.logger.info(f"Agent {task['agent']} started working on {task['task']}.")
        answer, reasoning = await self.agents[task["agent"].lower()].process(
            agent_prompt, None
        )
        self.last_answer = answer
        self.last_reasoning = reasoning
        self.blocks_result = self.agents[task["agent"].lower()].blocks_result
        agent_answer = self.agents[task["agent"].lower()].raw_answer_blocks(answer)
        success = self.agents[task["agent"].lower()].get_success
        self.agents[task["agent"].lower()].show_answer()
        pretty_print(f"Agent {task['agent']} completed task.", color="status")
        self.logger.info(
            f"Agent {task['agent']} finished working on {task['task']}. Success: {success}"
        )
        agent_answer += (
            "\nAgent succeeded with task."
            if success
            else "\nAgent failed with task (Error detected)."
        )
        return agent_answer, success

    def get_work_result_agent(self, task_needs, agents_work_result):
        res = {k: agents_work_result[k] for k in task_needs if k in agents_work_result}
        self.logger.info(
            f"Next agent needs: {task_needs}.\n Match previous agent result: {res}"
        )
        return res

    async def process(self, goal: str, speech_module: Speech) -> Tuple[str, str]:
        """
        Process the goal by dividing it into tasks and assigning them to agents.
        Args:
            goal (str): The goal to be achieved (user prompt).
            speech_module (Speech): The speech module for text-to-speech.
        Returns:
            Tuple[str, str]: The result of the agent process and empty reasoning string.
        """
        agents_tasks = []
        required_infos = None
        agents_work_result = dict()

        self.status_message = "Making a plan..."
        agents_tasks = await self.make_plan(goal)

        if agents_tasks == []:
            return "Failed to parse the tasks.", ""
        i = 0
        steps = len(agents_tasks)
        while i < steps and not self.stop:
            task_name, task = agents_tasks[i][0], agents_tasks[i][1]
            self.status_message = "Starting agents..."
            pretty_print(f"I will {task_name}.", color="info")
            self.last_answer = f"I will {task_name.lower()}."
            pretty_print(f"Assigned agent {task['agent']} to {task_name}", color="info")
            if speech_module:
                speech_module.speak(
                    f"I will {task_name}. I assigned the {task['agent']} agent to the task."
                )

            if agents_work_result is not None:
                required_infos = self.get_work_result_agent(
                    task["need"], agents_work_result
                )
            try:
                answer, success = await self.start_agent_process(task, required_infos)
            except Exception as e:
                raise e
            if self.stop:
                pretty_print(f"Requested stop.", color="failure")
            agents_work_result[task["id"]] = answer
            agents_tasks = await self.update_plan(
                goal, agents_tasks, agents_work_result, task["id"], success
            )
            steps = len(agents_tasks)
            i += 1

        return answer, ""
