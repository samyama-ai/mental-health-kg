"""Build and load the mental-health graph into Samyama."""
import click

@click.command()
@click.option("--limit", type=int, default=None, help="Cap rows per source for a fast demo load.")
def main(limit):
    # TODO: connect -> run schema/mental_health_kg.cypher -> load nodes/edges
    print(f"[loader] loading mental-health KG (limit={limit}) ...")

if __name__ == "__main__":
    main()
