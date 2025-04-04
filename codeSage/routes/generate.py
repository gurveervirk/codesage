import json
from llama_index.core.settings import Settings
from flask import Blueprint, request, jsonify, stream_with_context, Response, current_app
from code_sage.com_store import COMStore
from code_sage.sage_workflow import SageWorkflow

generate_bp = Blueprint('generate', __name__)

def generate_reply(prompt):
    try:
        llm = Settings.llm
        response = llm.stream_complete(prompt)
        for r in response:
            print(r)
            wrapped_data = {'wrapped_response': r.text}  # Encapsulate the response
            yield f"data: {json.dumps(wrapped_data)}\n\n"
    except Exception as e:
        print(f"Error in generate_reply: {e}")
        error_data = {'wrapped_response': f"Error: {e}"}  # Encapsulate the error
        yield f"data: {json.dumps(error_data)}\n\n"


@generate_bp.route('/generate-example', methods=['POST'])
def generate():
    data = request.get_json()
    try:
        prompt = data['prompt']
        return Response(stream_with_context(generate_reply(prompt)), content_type='text/event-stream') , 200
    except KeyError as e:
        print(f"KeyError: {e}")
        return jsonify({"error": "Invalid input, 'prompt' key is missing"}), 400
    except Exception as e:
        print(f"Error in generate: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        pass

# def generate_code(prompt:str):
#     try:
#         sage_workflow = SageWorkflow(com_store=current_app.com_store)
#         agent_workflow = sage_workflow.create_agent_workflow()
#         response = agent_workflow.stream
#     finally:
#         pass


# @generate_bp.route('/generate-code', methods=['POST'])
# def generate():
#     data = request.get_json()
#     try:
#         prompt = data['prompt']
#         return Response(stream_with_context(generate_reply(prompt)), content_type='text/event-stream') , 200
#     except KeyError as e:
#         print(f"KeyError: {e}")
#         return jsonify({"error": "Invalid input, 'prompt' key is missing"}), 400
#     except Exception as e:
#         print(f"Error in generate: {e}")
#         return jsonify({"error": str(e)}), 500
#     finally:
#         pass
    
