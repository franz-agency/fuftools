#!/usr/bin/env python3
# Copyright 2025 Franz und Franz GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
m1f-claude: Intelligent prompt enhancement for using Claude with m1f

This tool enhances your prompts to Claude by automatically providing context
about m1f capabilities and your project structure, making Claude much more
effective at helping you bundle and organize your code.
"""

import sys
import os
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, List
import argparse
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"  # Simple format for user-facing messages
)
logger = logging.getLogger(__name__)


class M1FClaude:
    """Enhance Claude prompts with m1f knowledge and context."""
    
    def __init__(self, project_path: Path = None):
        """Initialize m1f-claude with project context."""
        self.project_path = project_path or Path.cwd()
        self.m1f_root = Path(__file__).parent.parent
        self.m1f_docs_link = self.project_path / ".m1f" / "m1f-docs.txt"
        
        # Check if m1f-link has been run
        self.has_m1f_docs = self.m1f_docs_link.exists()
        
    def create_enhanced_prompt(self, user_prompt: str, context: Optional[Dict] = None) -> str:
        """Enhance user prompt with m1f context and best practices."""
        
        # Start with a strong foundation
        enhanced = []
        
        # Add m1f context
        enhanced.append("🚀 m1f Context Enhancement Active\n")
        enhanced.append("=" * 50)
        
        # Core m1f knowledge injection
        if self.has_m1f_docs:
            enhanced.append(f"""
m1f (Make One File) is installed and ready to use in this project.

📚 Complete m1f documentation is available at: @{self.m1f_docs_link.relative_to(self.project_path)}

This documentation includes:
- All m1f commands and parameters
- Preset system for file-specific processing
- Auto-bundle configuration with YAML
- Security scanning and encoding handling
- Integration with html2md, webscraper, and other tools
""")
        else:
            enhanced.append("""
⚠️  m1f documentation not linked yet. Run 'm1f-link' first to give me full context!

Without the docs, I'll use my general knowledge of m1f, but I'll be much more helpful
if you run 'm1f-link' and then reference @.m1f/m1f-docs.txt
""")
        
        # Add project context
        enhanced.append(self._analyze_project_context())
        
        # Add user's original prompt
        enhanced.append("\n" + "=" * 50)
        enhanced.append("\n🎯 User Request:\n")
        enhanced.append(user_prompt)
        
        # Add helpful hints based on common patterns
        enhanced.append("\n\n💡 m1f Quick Reference:")
        enhanced.append(self._get_contextual_hints(user_prompt))
        
        return "\n".join(enhanced)
    
    def _analyze_project_context(self) -> str:
        """Analyze the current project structure for better context."""
        context_parts = ["\n📁 Project Context:"]
        
        # Check for common project files
        config_files = {
            ".m1f.config.yml": "✅ Auto-bundle config found",
            "package.json": "📦 Node.js project detected",
            "requirements.txt": "🐍 Python project detected",
            "composer.json": "🎼 PHP project detected",
            "Gemfile": "💎 Ruby project detected",
            "Cargo.toml": "🦀 Rust project detected",
            "go.mod": "🐹 Go project detected",
            ".git": "📚 Git repository",
        }
        
        detected = []
        for file, desc in config_files.items():
            if (self.project_path / file).exists():
                detected.append(f"  {desc}")
        
        if detected:
            context_parts.extend(detected)
        else:
            context_parts.append("  📂 Standard project structure")
        
        # Check for m1f bundles
        m1f_dir = self.project_path / ".m1f"
        if m1f_dir.exists() and m1f_dir.is_dir():
            bundles = list(m1f_dir.glob("*.txt"))
            if bundles:
                context_parts.append(f"\n📦 Existing m1f bundles: {len(bundles)} found")
                for bundle in bundles[:3]:  # Show first 3
                    context_parts.append(f"  • {bundle.name}")
                if len(bundles) > 3:
                    context_parts.append(f"  • ... and {len(bundles) - 3} more")
        
        return "\n".join(context_parts)
    
    def _get_contextual_hints(self, user_prompt: str) -> str:
        """Provide contextual hints based on the user's prompt."""
        hints = []
        prompt_lower = user_prompt.lower()
        
        # Detect intent and provide relevant hints
        if any(word in prompt_lower for word in ["bundle", "combine", "merge"]):
            hints.append("""
- Basic bundling: m1f -s . -o output.txt
- With presets: m1f --preset wordpress -o bundle.txt
- Auto-bundle: m1f-update (if .m1f.config.yml exists)
""")
        
        if any(word in prompt_lower for word in ["config", "configure", "setup"]):
            hints.append("""
- Create .m1f.config.yml for auto-bundling
- Use presets for file-specific processing
- Set up exclude/include patterns
""")
        
        if any(word in prompt_lower for word in ["wordpress", "wp", "theme", "plugin"]):
            hints.append("""
- WordPress preset available: --preset presets/wordpress.m1f-presets.yml
- Excludes vendor/node_modules automatically
- Handles PHP/CSS/JS with appropriate processing
""")
        
        if any(word in prompt_lower for word in ["ai", "context", "assistant"]):
            hints.append("""
- Keep bundles under 100KB for AI context windows
- Use Markdown separator style for AI readability
- Create topic-specific bundles, not everything at once
""")
        
        if any(word in prompt_lower for word in ["test", "tests", "testing"]):
            hints.append("""
- Exclude tests: --excludes "**/test_*" "**/*_test.*"
- Or create test-only bundle for QA team
- Use include_extensions to filter by file type
""")
        
        return "\n".join(hints) if hints else "\nAsk me anything about bundling, organizing, or processing your files!"
    
    def send_to_claude_code(self, enhanced_prompt: str) -> Optional[str]:
        """Send the enhanced prompt to Claude Code if available."""
        try:
            # Check if claude command exists
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.info("\n📝 Claude Code not found. Here's your enhanced prompt to copy:\n")
                return None
                
            # Send to Claude Code
            logger.info("\n🤖 Sending to Claude Code...\n")
            
            # Create a temporary file with the prompt to handle complex prompts
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(enhanced_prompt)
                temp_path = f.name
            
            try:
                result = subprocess.run(
                    ["claude", "-f", temp_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    return result.stdout
                else:
                    logger.error(f"Claude Code error: {result.stderr}")
                    return None
            finally:
                os.unlink(temp_path)
                
        except FileNotFoundError:
            logger.info("\n📝 Claude Code not installed. Install with: npm install -g @anthropic-ai/claude-code")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Claude Code timed out")
            return None
        except Exception as e:
            logger.error(f"Error communicating with Claude Code: {e}")
            return None
    
    def interactive_mode(self):
        """Run in interactive mode for continued conversation."""
        print("\n🤖 m1f-claude Interactive Mode")
        print("=" * 50)
        print("I'll enhance your prompts with m1f knowledge!")
        print("Commands: 'help', 'context', 'examples', 'quit'\n")
        
        if not self.has_m1f_docs:
            print("💡 Tip: Run 'm1f-link' first for better assistance!\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("\n👋 Happy bundling!")
                    break
                    
                if user_input.lower() == 'help':
                    self._show_help()
                    continue
                    
                if user_input.lower() == 'context':
                    print(self._analyze_project_context())
                    continue
                    
                if user_input.lower() == 'examples':
                    self._show_examples()
                    continue
                
                # Enhance and process the prompt
                enhanced = self.create_enhanced_prompt(user_input)
                
                # Try to send to Claude Code
                response = self.send_to_claude_code(enhanced)
                
                if response:
                    print(f"\nClaude: {response}\n")
                else:
                    print("\n--- Enhanced Prompt ---")
                    print(enhanced)
                    print("\n--- Copy the above and paste into Claude! ---\n")
                    
            except KeyboardInterrupt:
                print("\n\nUse 'quit' to exit properly")
            except Exception as e:
                logger.error(f"Error: {e}")
    
    def _show_help(self):
        """Show help information."""
        print("""
🎯 m1f-claude Help

Commands:
  help     - Show this help
  context  - Show current project context
  examples - Show example prompts
  quit     - Exit interactive mode

Tips:
  • Run 'm1f-link' first for best results
  • Be specific about your project type
  • Mention constraints (file size, AI context windows)
  • Ask for complete .m1f.config.yml examples
""")
    
    def _show_examples(self):
        """Show example prompts that work well."""
        print("""
📚 Example Prompts That Work Great:

1. "Help me set up m1f for my Django project with separate bundles for models, views, and templates"

2. "Create a .m1f.config.yml that bundles my React app for code review, excluding tests and node_modules"

3. "I need to prepare documentation for a new developer. Create bundles that explain the codebase structure"

4. "Optimize my WordPress theme for AI assistance - create focused bundles under 100KB each"

5. "My project has Python backend and Vue frontend. Set up bundles for each team"

6. "Create a bundle of just the files that changed in the last week"

7. "Help me use m1f with GitHub Actions to auto-generate documentation bundles"
""")


def main():
    """Main entry point for m1f-claude."""
    parser = argparse.ArgumentParser(
        description="Enhance your Claude prompts with m1f knowledge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  m1f-claude "Help me bundle my Python project"
  m1f-claude -i                    # Interactive mode
  m1f-claude --check              # Check setup status
  
First time? Run 'm1f-link' to give Claude full m1f documentation!
"""
    )
    
    parser.add_argument(
        'prompt',
        nargs='*',
        help='Your prompt to enhance with m1f context'
    )
    
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Run in interactive mode'
    )
    
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check m1f-claude setup status'
    )
    
    parser.add_argument(
        '--no-send',
        action='store_true',
        help="Don't send to Claude Code, just show enhanced prompt"
    )
    
    args = parser.parse_args()
    
    # Initialize m1f-claude
    m1f_claude = M1FClaude()
    
    # Check status
    if args.check:
        print("\n🔍 m1f-claude Status Check")
        print("=" * 50)
        print(f"✅ m1f-claude installed and ready")
        print(f"📁 Working directory: {m1f_claude.project_path}")
        
        if m1f_claude.has_m1f_docs:
            print(f"✅ m1f docs linked at: {m1f_claude.m1f_docs_link.relative_to(m1f_claude.project_path)}")
        else:
            print(f"⚠️  m1f docs not linked - run 'm1f-link' first!")
        
        # Check for Claude Code
        try:
            result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ Claude Code is installed")
            else:
                print(f"⚠️  Claude Code not found - install with: npm install -g @anthropic-ai/claude-code")
        except:
            print(f"⚠️  Claude Code not found - install with: npm install -g @anthropic-ai/claude-code")
        
        return
    
    # Interactive mode
    if args.interactive or not args.prompt:
        m1f_claude.interactive_mode()
        return
    
    # Single prompt mode
    prompt = ' '.join(args.prompt)
    enhanced = m1f_claude.create_enhanced_prompt(prompt)
    
    if args.no_send:
        print("\n--- Enhanced Prompt ---")
        print(enhanced)
    else:
        response = m1f_claude.send_to_claude_code(enhanced)
        if response:
            print(response)
        else:
            print("\n--- Enhanced Prompt (copy this to Claude) ---")
            print(enhanced)


if __name__ == "__main__":
    main()