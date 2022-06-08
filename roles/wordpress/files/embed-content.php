<?php
/**
 * Contains the post embed content template part
 *
 * When a post is embedded in an iframe, this file is used to create the content template part
 * output if the active theme does not include an embed-content.php template.
 *
 * @package WordPress
 * @subpackage Theme_Compat
 * @since 4.5.0
 */
?>
    <style>

    .wp-embed {
        padding: 20px !important;
        border: 2px solid #eee;
        color: #333;
        box-shadow: none;
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", Roboto, Helvetica, Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif;
        font-size: 18px;
        line-height: 170%;
    }

    @media only screen and (max-width: 480px) {
        .wp-embed-featured-image.square {
            float: none;
            max-width: 100%;
            margin-right: 0;
            margin-bottom: 8px;
        }
    }

    p.wp-embed-heading {
        margin: 0 0 8px;
        color: #333;
        font-weight: 700;
        font-size: 1em;
        line-height: 1.5;
    }

    .wp-embed-excerpt p {
        font-size: 0.85em;
        line-height: 1.5;
        overflow: auto;
    }

    @media (min-width: 480px) {
        .wp-embed-excerpt p {
            text-align: justify;
        }
    }

    .wp-embed-footer {
        margin-top: 12px;
    }

    .wp-embed-site-icon {
        width: 18px;
        height: 18px;
    }

    .wp-embed-site-title {
        font-weight: normal;
        font-size: 0.85em;
        line-height: 1.5;
    }

    .wp-embed-site-title a {
        padding-left: 30px;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --base: #282c34;
            --mono-0: #dde1eb;
            --mono-1: #abb2bf;
            --mono-2: #818896;
            --mono-3: #5c6370;
            --mono-4: #404652;
            --mono-4-2: #343942;
            --hue-1: #56b6c2;
            --hue-2: #61aeee;
            --hue-3: #c678dd;
            --hue-4: #98c379;
            --hue-5: #e06c75;
            --hue-5-2: #be5046;
            --hue-6: #d19a66;
            --hue-6-2: #e6c07b;
            --theme-0: #29CED6;
            --theme: #21a4ac;
        }

        body {
            background: var(--mono-4-2);
        }

        .wp-embed {
            background: var(--base);
            color: var(--mono-0);
            border: 2px solid var(--mono-4);
        }

        .wp-embed a {
            color: var(--mono-1);
        }

        p.wp-embed-heading,
        p.wp-embed-heading a {
            color: var(--mono-0);
        }
    }

    </style>

    <div <?php post_class( 'wp-embed' ); ?>>
        <?php
        $thumbnail_id = 0;

        if ( has_post_thumbnail() ) {
            $thumbnail_id = get_post_thumbnail_id();
        }

        if ( 'attachment' === get_post_type() && wp_attachment_is_image() ) {
            $thumbnail_id = get_the_ID();
        }

        /**
         * Filters the thumbnail image ID for use in the embed template.
         *
         * @since 4.9.0
         *
         * @param int|false $thumbnail_id Attachment ID, or false if there is none.
         */
        $thumbnail_id = apply_filters( 'embed_thumbnail_id', $thumbnail_id );

        if ( $thumbnail_id ) {
            $aspect_ratio = 1;
            $measurements = array( 1, 1 );
            $image_size   = 'full'; // Fallback.

            $meta = wp_get_attachment_metadata( $thumbnail_id );
            if ( ! empty( $meta['sizes'] ) ) {
                foreach ( $meta['sizes'] as $size => $data ) {
                    if ( $data['height'] > 0 && $data['width'] / $data['height'] > $aspect_ratio ) {
                        $aspect_ratio = $data['width'] / $data['height'];
                        $measurements = array( $data['width'], $data['height'] );
                        $image_size   = $size;
                    }
                }
            }

            /**
             * Filters the thumbnail image size for use in the embed template.
             *
             * @since 4.4.0
             * @since 4.5.0 Added `$thumbnail_id` parameter.
             *
             * @param string $image_size   Thumbnail image size.
             * @param int    $thumbnail_id Attachment ID.
             */
            $image_size = apply_filters( 'embed_thumbnail_image_size', $image_size, $thumbnail_id );

            $shape = 'square';

            /**
             * Filters the thumbnail shape for use in the embed template.
             *
             * Rectangular images are shown above the title while square images
             * are shown next to the content.
             *
             * @since 4.4.0
             * @since 4.5.0 Added `$thumbnail_id` parameter.
             *
             * @param string $shape        Thumbnail image shape. Either 'rectangular' or 'square'.
             * @param int    $thumbnail_id Attachment ID.
             */
            $shape = apply_filters( 'embed_thumbnail_image_shape', $shape, $thumbnail_id );
        }

        if ( $thumbnail_id && 'square' === $shape ) :
            ?>
            <div class="wp-embed-featured-image square">
                <a href="<?php the_permalink(); ?>" target="_top">
                    <?php echo wp_get_attachment_image( $thumbnail_id, $image_size ); ?>
                </a>
            </div>
        <?php endif; ?>

        <p class="wp-embed-heading">
            <a href="<?php the_permalink(); ?>" target="_top">
                <?php the_title(); ?>
            </a>
        </p>

        <div class="wp-embed-excerpt"><?php the_excerpt_embed(); ?></div>

        <?php
        /**
         * Prints additional content after the embed excerpt.
         *
         * @since 4.4.0
         */
        do_action( 'embed_content' );
        ?>

        <div class="wp-embed-footer">
            <?php the_embed_site_title(); ?>
        </div>
    </div>
<?php
