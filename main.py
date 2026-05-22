# argparse is Python's built-in library for building command line interfaces
# it lets us define commands and arguments like:
# python main.py prep --sections 5 8 --simulate
# python main.py scenario-b
# python main.py sections
import argparse

# os gives us access to environment variables and file system operations
import os

# json is used to save and read the scenario B output files
import json

# datetime is used to timestamp our session results
from datetime import datetime

# rich is a terminal formatting library that makes output look nice
# Console is the main object we use to print colored/formatted text
# Panel draws a box around text for headers
# Table draws formatted tables in the terminal
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# load_dotenv reads our .env file so all environment variables are available
from dotenv import load_dotenv

# import all our core functions
# initialize_db sets up the SQLite database tables on first run
from core.kb import (
    initialize_db,
    save_session_with_mcqs,
    get_kb_snapshot,
    generate_session_id
)

# get_sections extracts section text from the PDF
# list_all_sections returns previews of all 10 sections
from core.pdf_parser import get_sections, list_all_sections

# generate_mcqs calls the Groq API to generate MCQ questions
from core.llm import generate_mcqs

# analyze_history checks the KB for prior session history
# simulate_answers auto-generates answers for scenario B
# build_adaptive_summary makes a human-readable history summary
from core.adaptive import (
    analyze_history,
    simulate_answers,
    build_adaptive_summary
)

# import our data models for building session results
from models.schemas import SessionResult, AnswerResult, PrepRequest

# save_scenario_output saves the required JSON files for scenario B
from api.routes import save_scenario_output

# load .env file before doing anything else
load_dotenv()

# create the rich Console object for pretty terminal output
# we use this instead of plain print() throughout main.py
console = Console()


def cmd_list_sections():
    """
    Handles the 'sections' command.
    Lists all 10 sections of the dossier with a short preview.
    The user runs this first to see what sections are available.

    Usage: python main.py sections
    """

    console.print(Panel(
        "[bold cyan]SLATEFALL Dossier — Available Sections[/bold cyan]",
        expand=False
    ))

    try:
        # get all section previews from the PDF parser
        previews = list_all_sections()

        # create a rich Table to display the sections nicely
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Section", style="cyan", width=10)
        table.add_column("Preview", style="white")

        # add each section as a row in the table
        for num, preview in sorted(previews.items()):
            table.add_row(str(num), preview[:120] + "...")

        console.print(table)

    except FileNotFoundError as e:
        # if the PDF is missing print a clear error message
        console.print(f"[bold red]ERROR:[/bold red] {e}")


def run_prep_flow(
    section_ids: list[int],
    simulate: bool = False,
    iteration: int = None,
    output_dir: str = None
) -> dict:
    """
    The core prep flow function used by both the 'prep' command
    and the 'scenario-b' command.

    Implements the full 5-step PREP FLOW from the assessment spec:
    STEP 1: Check KB for prior history
    STEP 2: Generate MCQs using LLM
    STEP 3: Present questions and collect answers
    STEP 4: Score the session
    STEP 5: Persist results to KB

    Parameters:
        section_ids : list of section IDs to study e.g. [5, 8]
        simulate    : if True auto-generate answers (for scenario B)
        iteration   : scenario B iteration number (1, 2, or 3)
        output_dir  : where to save scenario B output files

    Returns a dict with session results.
    """

    # make sure the database is initialized before anything else
    initialize_db()

    console.print(Panel(
        f"[bold cyan]Starting Prep Session — Sections: {section_ids}[/bold cyan]",
        expand=False
    ))

    # --- STEP 1: Check KB for prior history ---
    console.print("\n[bold yellow]STEP 1:[/bold yellow] Checking knowledge base for prior history...")

    # analyze_history queries the KB and returns adaptive context
    adaptive_context = analyze_history(section_ids)

    # print the adaptive summary so the user can see
    # whether this is a cold start or a returning run
    summary = build_adaptive_summary(section_ids)
    console.print(f"[dim]{summary}[/dim]\n")

    # --- STEP 2: Generate MCQs using LLM ---
    console.print("[bold yellow]STEP 2:[/bold yellow] Generating MCQs via Groq LLM...")

    # extract the text of the requested sections from the PDF
    sections = get_sections(section_ids)

    # generate MCQs for each section
    all_mcqs = []
    for section_id, section_text in sections.items():

        console.print(f"  [dim]Generating questions for Section {section_id}...[/dim]")

        # generate MCQs with adaptive context from the KB
        mcqs = generate_mcqs(
            section_id=section_id,
            section_text=section_text,
            # pass weak topics so LLM focuses on them
            weak_topics=adaptive_context["weak_topics"],
            # pass mastered topics so LLM avoids repeating them
            mastered_topics=adaptive_context["mastered_topics"],
            # tells LLM whether to use adaptive prompting
            is_returning=adaptive_context["is_returning"]
        )

        all_mcqs.extend(mcqs)
        console.print(f"  [green]✓[/green] Generated {len(mcqs)} questions for Section {section_id}")

    console.print(f"\n[green]Total questions generated: {len(all_mcqs)}[/green]\n")

    # --- STEP 3: Present questions and collect answers ---
    console.print("[bold yellow]STEP 3:[/bold yellow] Collecting answers...\n")

    if simulate:
        # simulate answers automatically for scenario B
        console.print("[dim]Simulating answers (65% correct rate)...[/dim]")
        raw_answers = simulate_answers(all_mcqs)

    else:
        # real interactive mode — ask the user each question
        raw_answers = []

        for i, mcq in enumerate(all_mcqs):

            # print the question with a nice panel
            console.print(Panel(
                f"[bold]Q{i+1}.[/bold] {mcq.question_text}",
                title=f"Section {mcq.section_id} | Topic: {mcq.topic_tag}",
                expand=False
            ))

            # print each choice
            for choice in mcq.choices:
                console.print(f"  [cyan]{choice.label}.[/cyan] {choice.text}")

            # keep asking until we get a valid answer
            while True:
                answer = input("\nYour answer (A/B/C/D): ").strip().upper()
                if answer in ["A", "B", "C", "D"]:
                    break
                console.print("[red]Invalid input. Please enter A, B, C, or D.[/red]")

            raw_answers.append({
                "question_id": mcq.question_id,
                "selected": answer
            })

            console.print()

    # --- STEP 4: Score the session ---
    console.print("[bold yellow]STEP 4:[/bold yellow] Scoring session...\n")

    # build a lookup dict from question_id to MCQ object
    mcq_lookup = {mcq.question_id: mcq for mcq in all_mcqs}

    # score each answer
    results = []
    score = 0

    for answer in raw_answers:
        mcq = mcq_lookup[answer["question_id"]]

        # check if the answer matches the correct answer
        is_correct = answer["selected"] == mcq.correct_answer

        if is_correct:
            score += 1

        # build the AnswerResult object for this question
        result = AnswerResult(
            question_id=mcq.question_id,
            question_text=mcq.question_text,
            selected=answer["selected"],
            correct_answer=mcq.correct_answer,
            is_correct=is_correct,
            explanation=mcq.explanation
        )
        results.append(result)

    # print results table to the terminal
    results_table = Table(show_header=True, header_style="bold magenta")
    results_table.add_column("Q#", width=4)
    results_table.add_column("Question", width=40)
    results_table.add_column("Selected", width=10)
    results_table.add_column("Correct", width=10)
    results_table.add_column("Result", width=10)

    for i, result in enumerate(results):
        # green tick for correct, red cross for wrong
        status = "[green]✓ Correct[/green]" if result.is_correct else "[red]✗ Wrong[/red]"
        results_table.add_row(
            str(i + 1),
            result.question_text[:38] + "..",
            result.selected,
            result.correct_answer,
            status
        )

    console.print(results_table)

    # print wrong answer explanations
    wrong_results = [r for r in results if not r.is_correct]
    if wrong_results:
        console.print("\n[bold red]Clarifications for wrong answers:[/bold red]")
        for r in wrong_results:
            console.print(Panel(
                f"[bold]Q:[/bold] {r.question_text}\n"
                f"[red]Your answer:[/red] {r.selected}\n"
                f"[green]Correct answer:[/green] {r.correct_answer}\n"
                f"[yellow]Explanation:[/yellow] {r.explanation}",
                expand=False
            ))

    # print final score
    percentage = round((score / len(all_mcqs)) * 100, 1)
    console.print(Panel(
        f"[bold green]Score: {score}/{len(all_mcqs)} ({percentage}%)[/bold green]",
        expand=False
    ))

    # build the session result object
    session_id = generate_session_id()
    session_result = SessionResult(
        session_id=session_id,
        section_ids=section_ids,
        timestamp=datetime.now().isoformat(),
        score=score,
        total=len(all_mcqs),
        results=results
    )

    # --- STEP 5: Persist results to KB ---
    console.print("\n[bold yellow]STEP 5:[/bold yellow] Saving session to knowledge base...")

    # save session with full MCQ data
    save_session_with_mcqs(
        session_result=session_result,
        mcqs=all_mcqs,
        simulated=simulate
    )

    console.print("[green]✓ Session saved to KB[/green]\n")

    # save scenario B output files if this is a scenario B run
    if iteration is not None and output_dir is not None:
        console.print(f"[bold yellow]Saving scenario B outputs for iteration {iteration}...[/bold yellow]")

        # save_scenario_output writes the required JSON files
        output_files = save_scenario_output(
            session_result=session_result,
            mcqs=all_mcqs,
            iteration=iteration,
            output_dir=output_dir
        )

        console.print(f"[green]✓ Saved:[/green] {output_files['questions_file']}")
        console.print(f"[green]✓ Saved:[/green] {output_files['snapshot_file']}")

    return {
        "session_id": session_id,
        "score": score,
        "total": len(all_mcqs),
        "percentage": percentage
    }


def cmd_prep(args):
    """
    Handles the 'prep' command.
    Runs a single prep session for the given sections.

    Usage:
        python main.py prep --sections 1 3
        python main.py prep --sections 5 8 --simulate
    """

    # run the prep flow with the given sections
    run_prep_flow(
        section_ids=args.sections,
        simulate=args.simulate
    )


def cmd_scenario_b(args):
    """
    Handles the 'scenario-b' command.
    Runs the three required scenario B iterations automatically:

    Iter 1: sections 5, 8
    Iter 2: sections 6, 8, 9
    Iter 3: section 8

    Each iteration saves output files to the outputs/ folder.
    This is the core evaluation scenario from the assessment spec.

    Usage: python main.py scenario-b
    """

    console.print(Panel(
        "[bold cyan]Running Scenario B — 3 Iterations[/bold cyan]\n"
        "Iter 1: Sections 5, 8\n"
        "Iter 2: Sections 6, 8, 9\n"
        "Iter 3: Section 8",
        expand=False
    ))

    # define the three iterations exactly as specified in the assessment
    iterations = [
        # (iteration_number, section_ids, output_directory)
        (1, [5, 8],    "outputs/scenario_b_iter1"),
        (2, [6, 8, 9], "outputs/scenario_b_iter2"),
        (3, [8],       "outputs/scenario_b_iter3"),
    ]

    # run each iteration in sequence
    # each iteration builds on the KB history from previous ones
    # this is what demonstrates the adaptive behavior
    for iteration, section_ids, output_dir in iterations:

        console.print(Panel(
            f"[bold magenta]ITERATION {iteration}[/bold magenta] — "
            f"Sections: {section_ids}",
            expand=False
        ))

        # run the prep flow for this iteration
        # simulate=True because we don't need a real human for evaluation
        # iteration and output_dir trigger saving the required JSON files
        result = run_prep_flow(
            section_ids=section_ids,
            simulate=True,
            iteration=iteration,
            output_dir=output_dir
        )

        console.print(
            f"[green]Iteration {iteration} complete.[/green] "
            f"Score: {result['score']}/{result['total']} "
            f"({result['percentage']}%)\n"
        )

    console.print(Panel(
        "[bold green]Scenario B Complete![/bold green]\n"
        "Output files saved to outputs/scenario_b_iter1/\n"
        "                    outputs/scenario_b_iter2/\n"
        "                    outputs/scenario_b_iter3/",
        expand=False
    ))


def cmd_snapshot(args):
    """
    Handles the 'snapshot' command.
    Prints the current KB snapshot to the terminal.
    Shows the 5 most recent sessions with question-level results.

    Usage: python main.py snapshot
    """

    # make sure the DB is initialized
    initialize_db()

    # get the snapshot from the KB
    snapshot = get_kb_snapshot()

    # print it as formatted JSON
    console.print(Panel(
        "[bold cyan]Knowledge Base Snapshot[/bold cyan]",
        expand=False
    ))

    # json.dumps with indent=2 makes it human-readable
    console.print(json.dumps(snapshot, indent=2))


def main():
    """
    Entry point of the application.
    Sets up the argument parser and routes commands to the right function.

    Available commands:
        sections    — list all available sections
        prep        — run a prep session
        scenario-b  — run all 3 scenario B iterations
        snapshot    — print the current KB snapshot
    """

    # create the main argument parser
    # description appears when the user runs: python main.py --help
    parser = argparse.ArgumentParser(
        description="SLATEFALL Adaptive Document Preparation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py sections
  python main.py prep --sections 1 3
  python main.py prep --sections 5 8 --simulate
  python main.py scenario-b
  python main.py snapshot
        """
    )

    # subparsers lets us define multiple sub-commands
    # each sub-command has its own arguments
    subparsers = parser.add_subparsers(dest="command")

    # --- 'sections' command ---
    # no arguments needed, just lists available sections
    subparsers.add_parser(
        "sections",
        help="List all available sections in the dossier"
    )

    # --- 'prep' command ---
    prep_parser = subparsers.add_parser(
        "prep",
        help="Run a prep session for given sections"
    )
    prep_parser.add_argument(
        "--sections",
        # nargs='+' means one or more values
        # so --sections 5 8 gives us [5, 8]
        nargs="+",
        type=int,
        required=True,
        help="Section IDs to study e.g. --sections 5 8"
    )
    prep_parser.add_argument(
        "--simulate",
        # store_true means this flag is False by default
        # and becomes True when --simulate is passed
        action="store_true",
        help="Simulate answers instead of asking user"
    )

    # --- 'scenario-b' command ---
    # no arguments needed, runs all 3 iterations automatically
    subparsers.add_parser(
        "scenario-b",
        help="Run all 3 Scenario B iterations automatically"
    )

    # --- 'snapshot' command ---
    # no arguments needed, prints the current KB snapshot
    subparsers.add_parser(
        "snapshot",
        help="Print the current knowledge base snapshot"
    )

    # parse the arguments the user provided
    args = parser.parse_args()

    # if no command was given print help and exit
    if not args.command:
        parser.print_help()
        return

    # route to the correct function based on the command
    if args.command == "sections":
        cmd_list_sections()

    elif args.command == "prep":
        cmd_prep(args)

    elif args.command == "scenario-b":
        cmd_scenario_b(args)

    elif args.command == "snapshot":
        cmd_snapshot(args)


# this block only runs when main.py is executed directly
# it does NOT run when main.py is imported by another file
# this is standard Python practice for entry point scripts
if __name__ == "__main__":
    main()