# Project guidance

This is an academic research project in Python.

- Keep code simple, readable, and consistent with existing conventions.
- Make focused changes; avoid unnecessary abstractions and dependencies.
- Preserve raw data. Keep generated data, figures, and results separate from inputs.
- Make analyses reproducible: use explicit random seeds and document dependencies, parameters, and execution steps.
- Document scientific assumptions and methods. Do not fabricate data, results, or citations.
- Check affected code with relevant tests or a small reproducible example; report what was verified and any limitations.
- Use the associated uv environment to run Python
- Don't write markdown in Jupyter files
- Try to write the most minimal, most understandable code. In Python this usually means no asserts or type checking unless it's in high-performance code, like a neural network. Where dict and list literals can be used, write literals.
- Ask questions if anything at all is uncertain.
- When possible, use canonical packages for algorithms, rather than writing a new implementation from scratch 