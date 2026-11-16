"""A small command-line program made with simplycommand.

    python seqs.py count genes.fa --min-length 100
    python seqs.py lengths genes.fa
    python seqs.py --help
"""

import simplycommand as scmd


class Sequences(scmd.CommandLineProgram):
    """Small tools for FASTA files."""

    def count(self, fasta: str, min_length: int = 0):
        """Count the sequences in a FASTA file.
        fasta: the FASTA file to read
        min_length: only count sequences at least this long
        """
        return sum(1 for _, seq in read_fasta(fasta) if len(seq) >= min_length)

    def lengths(self, fasta: str, longest_first: bool = False):
        """Show the name and length of every sequence.
        fasta: the FASTA file to read
        longest_first: sort from the longest sequence to the shortest
        """
        rows = [(name, len(seq)) for name, seq in read_fasta(fasta)]
        if longest_first:
            rows.sort(key=lambda row: row[1], reverse=True)
        return "\n".join(f"{name}\t{length}" for name, length in rows)


def read_fasta(file_name):
    name, parts = None, []
    with open(file_name, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts)
                name, parts = line[1:].split()[0] if line[1:].strip() else "", []
            elif line:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


if __name__ == "__main__":
    Sequences().start_from_command_line()
