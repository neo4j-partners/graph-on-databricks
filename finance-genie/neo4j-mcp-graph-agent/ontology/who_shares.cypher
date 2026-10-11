MATCH (e:Entity)-[:EXTRACTED_FROM]->(:Message)<-[:HAS_MESSAGE]-(c:Conversation)
WHERE c.userId IS NOT NULL
WITH e, collect(DISTINCT c.userId) AS analysts
WHERE size(analysts) > 1
RETURN e.name AS name, e.type AS type, size(analysts) AS analysts, e.mentionCount AS mentions, e.id AS id
ORDER BY analysts DESC, mentions DESC
LIMIT 8
