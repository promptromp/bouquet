# Contributing to bouquet

Thank you for your interest in contributing to bouquet! We welcome contributions from the community and appreciate your help in making this project better.

## Getting Started

### Prerequisites

- Python 3.14 or higher
- Git
- A GitHub account
- tmux (for running the TUI)

### Setting Up Your Development Environment

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/bouquet.git
   cd bouquet
   ```
3. Install dependencies with uv:
   ```bash
   uv sync
   ```
4. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue using our **Bug Report** template. Include:

- A clear description of the problem
- Steps to reproduce the issue
- Expected vs actual behavior
- Your environment details (OS, Python version, tmux version)
- Any relevant error messages or logs

### Suggesting Features

We welcome feature suggestions! Please use our **Feature Request** template when creating an issue. Help us understand:

- The problem your feature would solve
- How you envision the feature working
- Any alternatives you've considered
- Whether you're willing to help implement it

### Contributing Code

1. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards:
   - Write clear, readable code
   - Follow PEP 8 style guidelines
   - Keep commits focused and atomic

3. **Add tests** for your changes:
   - All new functionality should include tests
   - Ensure existing tests still pass

4. **Run the checks**:
   ```bash
   uv run pytest tests/ -v
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run mypy src/ tests/
   ```

5. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Clear description of your changes"
   ```

6. **Push to your fork** and create a Pull Request on GitHub with:
   - A clear title and description
   - Reference to any related issues
   - Description of what you changed and why

### Code Style

- We use `ruff` for linting and formatting (line length: 120, target Python 3.14)
- Use type hints where appropriate
- Write clear commit messages
- See `CLAUDE.md` for full coding conventions

### Testing

- Write tests for all new functionality
- Ensure all tests pass before submitting a PR
- Include both positive and negative test cases
- See `CLAUDE.md` for testing patterns and fixtures

## Development Workflow

1. Check existing issues and PRs to avoid duplicate work
2. For significant changes, consider opening an issue first to discuss the approach
3. Create a focused branch for each feature or bug fix
4. Write clear, descriptive commit messages
5. Keep PRs reasonably sized and focused
6. Be responsive to feedback during code review

## Getting Help

- Check existing issues and documentation first
- Create a new issue if you need help or have questions
- Be patient and respectful in all interactions

## Code of Conduct

Please be respectful and constructive in all interactions. See our [Code of Conduct](CODE_OF_CONDUCT.md) for details.

## License

By contributing to bouquet, you agree that your contributions will be licensed under the same [MIT License](LICENSE) as the project.
