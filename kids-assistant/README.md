# Kids Homework Assistant (built on Open WebUI)

A safe, guided homework tutor for Estelle (Grade 6, Willard MS) and Dorian (Grade 4, Hovatter ES), Loudoun County Public Schools.

Status: **research and design.** No application changes yet.

## Contents

- `curriculum/dorian-grade4.md` — courses, math program (Kiddom / Illustrative Mathematics), required methods and worked examples
- `curriculum/estelle-grade6.md` — courses, schedule structure, math program (Mathspace), required methods and worked examples

These profiles become the knowledge base and system-prompt source for each child's tutor.

## Design principles

1. **Guide, don't answer.** LCPS Policy 5430 (generative AI, 2025) requires teacher approval for AI use on student work. The tutor coaches the child through problems and never hands over finished homework.
2. **Teach the classroom method.** The state standards define *what* is taught; the curriculum (IM for grade 4, Mathspace for grade 6) and the teacher define *how*. When unsure, the tutor asks "How did your teacher show you?"
3. **Layered safety, not a system prompt alone:**
   - a hosted model with strong safety behavior;
   - filter functions on input and output;
   - blocking of personal information;
   - escalation to a parent;
   - no web access;
   - parent-visible chat history.
4. **Per-child isolation.** Separate accounts and separate tutors; each child can see only their own chats and notes.

## Research gaps

- `www.doe.virginia.gov` is on this environment's allowlist, but VDOE's CDN (Akamai) returns *403 Access Denied* to automated clients. The full VDOE standards PDFs were not read directly; standards text comes from secondary sources that quote them. Fix: download the Grade 4 and Grade 6 Math SOL and Instructional Guide PDFs in a browser and add them under `curriculum/sources/`.
- Publisher sites (mathspace.co, illustrativemathematics.org, kiddom.co) are not on the allowlist.

## Sources

- LCPS Mathematics (core resources): https://www.lcps.org/o/dtl/page/mathematics
- LCPS core textbook announcements: https://www.lcps.org/o/dtl/page/public-announcements
- LCPS Program of Studies, middle school: https://sites.google.com/lcps.org/program-of-studies-2024-2025/middle-school-course-information (subject pages ms-math, ms-english, ms-science, ms-social-science, ms-hpe)
- Willard electives: https://www.willardmiddleschool.org/academics/electives/
- 2023 Virginia Math SOL K–12 (copy): https://www.baconsrebellion.com/wp-content/uploads/2023/12/00-Kthru12-Approved-2023-Math-SOL.pdf
- 4.CE.2 text: https://goblinsapp.com/standards/math/virginia/4-ce-2
- IM Grade 4 Unit 6: https://im.kendallhunt.com/K5/teachers/grade-4/unit-6/lessons.html
- IM Grade 4 Unit 6 family materials: https://im.kendallhunt.com/k5/families/grade-4/unit-6/family-materials.html
- Kiddom Virginia Math: https://www.kiddom.co/insights/introducing-kiddom-virginia-math
- VDOE approved math textbooks: https://www.doe.virginia.gov/teaching-learning-assessment/k-12-standards-instruction/mathematics/2024-mathematics-textbooks
- 2023 History & Social Science SOL FAQ: https://www.doe.virginia.gov/teaching-learning-assessment/k-12-standards-instruction/history-and-social-science/standards-of-learning/2023-history-and-social-science-sol-faq
- LCPS AI policy coverage: https://www.loudounnow.com/news/education/loudoun-school-board-approves-new-generative-ai-policy/article_9cf6150a-9c80-4714-909c-a88340cd56b7.html
