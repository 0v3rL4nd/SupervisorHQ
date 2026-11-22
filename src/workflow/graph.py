from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from src.core.state import PraticaUfficioState
from src.agents.supervisor import nodo_segreteria_smistamento, nodo_segreteria_risposta
from src.agents.admin_agent import nodo_amministrazione
from src.agents.sales_agent import nodo_commerciale
from src.agents.support_agent import nodo_assistenza
from src.agents.secretary_agent import nodo_agenda

def rotta_dallo_smistamento(state: PraticaUfficioState) -> str:
    """
    Il controllore dei binari. Legge la decisione presa dal Supervisore
    (forzata da Pydantic) e instrada il grafo.
    """
    reparto_scelto = state.get("prossimo_reparto")

    # Mappa le stringhe generate da Qwen/Pydantic ai nomi effettivi dei nodi del grafo
    mappa_destinazioni = {
        "AMMINISTRAZIONE": "nodo_amministrazione",
        "COMMERCIALE": "nodo_commerciale",
        "AGENDA": "nodo_agenda",
        "ASSISTENZA": "nodo_assistenza",
        "SEGRETERIA_RISPONDE": "nodo_segreteria_risposta"
    }

    return mappa_destinazioni.get(reparto_scelto, "nodo_segreteria_risposta")


def compila_grafo_ufficio():
    workflow = StateGraph(PraticaUfficioState)

    workflow.add_node("nodo_segreteria_smistamento", nodo_segreteria_smistamento)
    workflow.add_node("nodo_amministrazione", nodo_amministrazione)
    workflow.add_node("nodo_commerciale", nodo_commerciale)
    workflow.add_node("nodo_assistenza", nodo_assistenza)
    workflow.add_node("nodo_agenda", nodo_agenda)
    workflow.add_node("nodo_segreteria_risposta", nodo_segreteria_risposta)

    workflow.add_edge(START, "nodo_segreteria_smistamento")

    workflow.add_conditional_edges(
        "nodo_segreteria_smistamento",
        rotta_dallo_smistamento,
        {
            "nodo_amministrazione": "nodo_amministrazione",
            "nodo_commerciale": "nodo_commerciale",
            "nodo_assistenza": "nodo_assistenza",
            "nodo_agenda": "nodo_agenda",
            "nodo_segreteria_risposta": "nodo_segreteria_risposta"
        }
    )

    workflow.add_edge("nodo_amministrazione", "nodo_segreteria_risposta")
    workflow.add_edge("nodo_commerciale", "nodo_segreteria_risposta")
    workflow.add_edge("nodo_assistenza", "nodo_segreteria_risposta")
    workflow.add_edge("nodo_agenda", "nodo_segreteria_risposta")
    workflow.add_edge("nodo_segreteria_risposta", END)

    memoria = MemorySaver()
    # Compilazione del grafo CON BREAKPOINT UMANO
    # Il grafo si fermerà SEMPRE un attimo prima di inviare l'email finale.
    ufficio = workflow.compile(
        checkpointer=memoria,
        #interrupt_before=["nodo_segreteria_risposta"]
    )

    return ufficio