import os
import subprocess
import tempfile
import json
from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS

# --- Configuration ---
# Set a timeout for code execution (in seconds)
EXECUTION_TIMEOUT = 5

# --- Flask App Setup ---
app = Flask(__name__)
# Enable CORS for all routes, allowing requests from any origin.
# For more security in a real scenario, restrict the origins.
CORS(app)

# --- Helper Function to Run Subprocess ---
def run_subprocess(command, input_data=None, timeout=None):
    """Runs a command in a subprocess, capturing output and errors."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True, # Ensure output/error are strings
            input=input_data,
            timeout=timeout,
            check=False # Don't raise exception on non-zero exit code directly
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        # Indicate timeout specifically in stderr and return code
        return None, f"Execution timed out after {timeout} seconds.", -1
    except Exception as e:
        # Indicate other subprocess errors
        return None, f"Error running subprocess: {str(e)}", -2

# --- Main Execution Route ---
@app.route('/execute/python', methods=['POST'])
def execute_python():
    """
    Receives Python code, executes it, lints it, and returns results.
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    code = data.get('code')

    if code is None:
        return jsonify({"error": "Missing 'code' field in JSON payload"}), 400

    # Initialize variables
    output = ""
    error = ""
    lint_feedback = ""
    temp_file_path = None # Ensure temp_file_path is defined in the function scope

    try:
        # --- Create a temporary file to store the code ---
        # Using 'delete=False' so we can run flake8 on it before manual deletion.
        # The 'with' statement ensures the file handle is closed properly.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(code)
            # temp_file is automatically flushed and closed upon exiting the 'with' block

        # --- Execute the code ---
        # SECURITY WARNING: Running arbitrary code like this is dangerous without sandboxing!
        # This uses the system's default python interpreter found in the PATH.
        # Ensure the deployment environment has the correct Python version.
        exec_command = ['python', temp_file_path]
        exec_stdout, exec_stderr, return_code = run_subprocess(
            exec_command,
            timeout=EXECUTION_TIMEOUT
        )

        if exec_stdout is not None:
            output = exec_stdout
        # Combine potential stderr from execution with specific error messages
        if exec_stderr is not None:
            error += exec_stderr # Append stderr first

        # Add specific error context based on return code
        if return_code == -1: # Timeout indicator from helper
             error = f"Timeout Error: Execution exceeded {EXECUTION_TIMEOUT} seconds. {error}".strip()
        elif return_code == -2: # Subprocess run error indicator from helper
            error = f"Execution Error: Failed to run subprocess. {error}".strip()
        elif return_code != 0: # Actual non-zero exit code from the Python script
             # Add the exit code info if not already covered by stderr
             error_msg = f"Process exited with status code {return_code}."
             if error_msg not in error: # Avoid duplicating if stderr already mentioned it
                error = f"{error_msg} {error}".strip()

        # --- Lint the code using Flake8 ---
        # Ensure flake8 is installed in the environment (via requirements.txt)
        lint_command = ['flake8', temp_file_path]
        # Usually no timeout needed for linting, but could add one if required
        lint_stdout, lint_stderr, lint_return_code = run_subprocess(lint_command)

        if lint_stdout:
            # Format Flake8 output: Each line is a potential issue
            # Example line: temp_file_path:line:col: CODE message
            lines = lint_stdout.strip().split('\n')
            formatted_lines = []
            for line in lines:
                 # Remove the temporary file path prefix for cleaner output
                 # Split only 3 times to keep the rest of the message intact
                 parts = line.split(':', 3)
                 if len(parts) == 4:
                     formatted_lines.append(f"L{parts[1]}:{parts[2]}: {parts[3].strip()}")
                 else:
                     formatted_lines.append(line) # Keep original if format unexpected
            lint_feedback = "\n".join(formatted_lines)

        # Add Flake8's own errors if any occurred
        if lint_stderr:
             lint_feedback += f"\n--- Flake8 Error ---\n{lint_stderr}".strip()
        # Note: Flake8 returns non-zero exit code if lint issues are found.
        # We usually still want to show the lint_stdout in that case.


    except Exception as e:
        # Catch any other unexpected errors during file handling etc.
        error += f"\nServer Error during processing: {str(e)}"
    finally:
        # --- Clean up the temporary file ---
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                # Log this server-side, don't usually expose filesystem errors to client
                print(f"Warning: Failed to delete temporary file {temp_file_path}: {e}")


    # --- Return the results ---
    # Use .strip() to remove potential leading/trailing whitespace from outputs/errors
    return jsonify({
        "output": output.strip(),
        "error": error.strip(),
        "lint_feedback": lint_feedback.strip()
    })

# --- Flask Development Server Run ---
# This block is used for local development ONLY.
# Render will use the Gunicorn command specified in its settings.
if __name__ == '__main__':
    # Runs on http://127.0.0.1:5000 by default in debug mode
    # Use host='0.0.0.0' to make it accessible on your local network for testing
    # IMPORTANT: Set debug=False when deploying or using Gunicorn
    app.run(debug=True, host='0.0.0.0', port=5000)