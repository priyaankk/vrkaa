from flask import Flask, request, jsonify
import requests
import os
import json
from groq import Groq

app = Flask(__name__)

# Environment variables (set these in Render)
store_url = os.environ.get("STORE_URL")  # Your Shopify store URL
access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")  # Your Shopify access token
groq_api_key = os.environ.get("GROQ_API_KEY")  # Your Groq API key

def llama(q):
    """Fetch response from Llama using Groq API."""
    client = Groq(api_key=groq_api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "user", "content": q}
        ],
        model="llama-3.3-70b-versatile",
    )
    return chat_completion.choices[0].message.content

@app.route("/reorder", methods=["POST"])
def reorder_products():
    # Parse input JSON for the query prompt
    data = request.json
    search_prompt = data.get("search_prompt", "")
    search_terms = ['mouse''controller','headset','keyboard']

    # Select the best search term
    search_term = select_best_term(search_prompt, search_terms)

    # GraphQL query
    graphql_query = f"""
    query {{
      products(query: "{search_term}", first: 10) {{
        edges {{
          node {{
            id
            title
            description
            images(first: 1) {{
              edges {{
                node {{
                  url
                }}
              }}
            }}
            variants(first: 1) {{
              edges {{
                node {{
                  price {{
                    amount
                    currencyCode
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

    headers = {
        "X-Shopify-Storefront-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    # Send request to GraphQL API
    response = requests.post(store_url, json={"query": graphql_query}, headers=headers)

    if response.status_code == 200:
        data = response.json()
        products = extract_products(data)
        ranked_ids = rank_products(search_prompt, products)
        reordered_json = reorder_products_by_rank(data, ranked_ids)

        # Flatten the reordered data
        flattened_products = []
        for edge in reordered_json["data"]["products"]["edges"]:
            node = edge["node"]
            flattened_products.append({
                "id": node["id"],
                "title": node["title"],
                "description": node["description"],
                "image": node["images"]["edges"][0]["node"]["url"] if node["images"]["edges"] else None,
                "price": f"{node['variants']['edges'][0]['node']['price']['amount']} {node['variants']['edges'][0]['node']['price']['currencyCode']}"
            })

        # Save to a JSON file and return it as the response
        with open("reordered.json", "w") as f:
            json.dump(flattened_products, f, indent=2)

        return jsonify(flattened_products)  # Return the flattened JSON as the response

    return jsonify({"error": "Failed to fetch products", "status": response.status_code}), response.status_code

def select_best_term(query, search_terms):
    """Select the best search term using Llama."""
    prompt = (
        f"From the following list of terms: {', '.join(search_terms)}, "
        f"select the one that is most relevant to this query: \"{query}\". "
        "Return only the term."
    )
    best_term = llama(prompt)
    return best_term

def extract_products(json_data):
    """Extract product information from the JSON response."""
    products = []
    for edge in json_data["data"]["products"]["edges"]:
        node = edge["node"]
        product = {
            "id": node["id"],
            "title": node["title"],
            "description": node["description"],
            "price": node["variants"]["edges"][0]["node"]["price"]["amount"],
            "currency": node["variants"]["edges"][0]["node"]["price"]["currencyCode"],
        }
        products.append(product)
    return products

def rank_products(search_prompt, products):
    """Rank products using Llama based on relevance to the search prompt."""
    prompt = f"Rank these products by relevance to '{search_prompt}'.\n" + "\n".join(
        [f"{i+1}. {p['title']} - {p['description']} (Price: {p['price']} {p['currency']})" for i, p in enumerate(products)]
    )
    prompt += '\nReturn the ranked IDs as JSON: ["1","2","3"].'
    ranked_order = llama(prompt)
    try:
        return json.loads(ranked_order)
    except json.JSONDecodeError:
        return [p["id"] for p in products]

def reorder_products_by_rank(json_data, ranked_ids):
    """Reorder products based on ranked IDs."""
    product_dict = {str(index + 1): edge for index, edge in enumerate(json_data["data"]["products"]["edges"])}
    reordered_edges = [product_dict[rank_id] for rank_id in ranked_ids if rank_id in product_dict]
    json_data["data"]["products"]["edges"] = reordered_edges
    return json_data

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
